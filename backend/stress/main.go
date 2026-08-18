// Package main: 压测服务骨架。
//
// V1 压测内核为 go-stress-testing（Apache-2.0）扩展，独立 stress 容器，
// 由 worker 下发任务。本文件当前提供：
//   - GET /health          健康检查
//   - GET /metrics         Prometheus 指标（前缀 ai_eval_stress_，label env,model,task_id）
//   - POST /run            接收压测任务（骨架版仅记录，不真正压测）
//
// 真实压测实现（M4）需要在此接入 go-stress-testing 内核，见 PRD 5.6 / F-ST-01~07。
package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"
)

// StressJob 由 worker 下发的压测任务描述（骨架版字段）。
type StressJob struct {
	TaskID     string `json:"task_id"`
	Env        string `json:"env"`
	Model      string `json:"model"`
	URL        string `json:"url"`
	QPS        int    `json:"qps"`
	DurationS  int    `json:"duration_s"`
	SLAP99Ms   *int   `json:"sla_p99_ms,omitempty"`
}

var (
	mu       sync.Mutex
	lastJob  *StressJob
	jobState = "idle"
)

func main() {
	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("/metrics", handleMetrics)
	http.HandleFunc("/run", handleRun)

	addr := ":19090"
	log.Printf("stress service listening on %s", addr)
	if err := http.ListenAndServe(addr, nil); err != nil {
		log.Fatal(err)
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"status":"ok"}`))
}

// handleMetrics 输出 Prometheus 文本格式指标。
// 前缀与 label 遵循 PRD F-ST-04：ai_eval_stress_*，label 含 env,model,task_id。
func handleMetrics(w http.ResponseWriter, r *http.Request) {
	mu.Lock()
	defer mu.Unlock()

	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	env, model, taskID := "", "", ""
	if lastJob != nil {
		env, model, taskID = lastJob.Env, lastJob.Model, lastJob.TaskID
	}
	fmt.Fprintf(w, "# HELP ai_eval_stress_qps 当前 QPS\n# TYPE ai_eval_stress_qps gauge\n")
	fmt.Fprintf(w, "ai_eval_stress_qps{env=%q,model=%q,task_id=%q} %d\n", env, model, taskID, 0)
	fmt.Fprintf(w, "# HELP ai_eval_stress_rt_ms 平均响应时间\n# TYPE ai_eval_stress_rt_ms gauge\n")
	fmt.Fprintf(w, "ai_eval_stress_rt_ms{env=%q,model=%q,task_id=%q} %d\n", env, model, taskID, 0)
	fmt.Fprintf(w, "# HELP ai_eval_stress_error_rate 错误率(0-1)\n# TYPE ai_eval_stress_error_rate gauge\n")
	fmt.Fprintf(w, "ai_eval_stress_error_rate{env=%q,model=%q,task_id=%q} %f\n", env, model, taskID, 0.0)
}

func handleRun(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var job StressJob
	if err := json.NewDecoder(r.Body).Decode(&job); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}

	mu.Lock()
	lastJob = &job
	jobState = "running"
	mu.Unlock()

	log.Printf("received stress job: task=%s env=%s model=%s qps=%d duration=%ds",
		job.TaskID, job.Env, job.Model, job.QPS, job.DurationS)

	// 骨架版：模拟执行 duration（上限 5s 避免阻塞），真实内核在 M4 接入。
	sim := job.DurationS
	if sim > 5 {
		sim = 5
	}
	time.Sleep(time.Duration(sim) * time.Second)

	mu.Lock()
	jobState = "idle"
	mu.Unlock()

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{"status": "done", "task_id": job.TaskID})
}
