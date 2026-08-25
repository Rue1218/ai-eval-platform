// Package main: 压测服务。由 Worker 下发任务，本容器独占发压，不在 api 进程内跑。
//
//   - GET  /health            健康检查
//   - GET  /metrics           Prometheus（前缀 ai_eval_stress_，label env,model,task_id）
//   - POST /run               异步启动发压，立即返回 accepted
//   - GET  /status?task_id=   当前快照（含 time_series）
//   - POST /stop              {"task_id"} 立即停发
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"sort"
	"sync"
	"time"
)

// StressJob 由 Worker 下发的压测任务。Headers 含鉴权，禁止写入日志。
type StressJob struct {
	TaskID    string            `json:"task_id"`
	Env       string            `json:"env"`
	Model     string            `json:"model"`
	URL       string            `json:"url"`
	Method    string            `json:"method"`
	Headers   map[string]string `json:"headers"`
	Body      json.RawMessage   `json:"body"`
	QPS       int               `json:"qps"`
	DurationS int               `json:"duration_s"`
	SLAP99Ms  *int              `json:"sla_p99_ms,omitempty"`
}

type seriesPoint struct {
	TS        string  `json:"ts"`
	QPS       float64 `json:"qps"`
	RTMs      float64 `json:"rt_ms"`
	ErrorRate float64 `json:"error_rate"`
}

type jobSnapshot struct {
	Status     string        `json:"status"`
	TaskID     string        `json:"task_id"`
	QPS        float64       `json:"qps"`
	RTMs       float64       `json:"rt"`
	P99Ms      float64       `json:"p99_ms"`
	ErrorRate  float64       `json:"error_rate"`
	TTFTMs     *float64      `json:"ttft_ms,omitempty"`
	TimeSeries []seriesPoint `json:"time_series"`
	SLAMet     *bool         `json:"sla_met,omitempty"`
	Total      int           `json:"total"`
	Errors     int           `json:"errors"`
}

type runningJob struct {
	job    StressJob
	cancel context.CancelFunc

	mu         sync.Mutex
	status     string
	ok         int
	err        int
	latencies  []float64
	windowOK   int
	windowErr  int
	windowLat  []float64
	series     []seriesPoint
	started    time.Time
	finished   time.Time
}

var (
	jobsMu sync.Mutex
	jobs   = map[string]*runningJob{}
)

func main() {
	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("/metrics", handleMetrics)
	http.HandleFunc("/run", handleRun)
	http.HandleFunc("/status", handleStatus)
	http.HandleFunc("/stop", handleStop)

	addr := ":19090"
	log.Printf("stress service listening on %s", addr)
	if err := http.ListenAndServe(addr, nil); err != nil {
		log.Fatal(err)
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"status":"ok"}`))
}

func handleMetrics(w http.ResponseWriter, r *http.Request) {
	snap, job := latestSnapshot()
	env, model, taskID := "", "", ""
	if job != nil {
		env, model, taskID = job.Env, job.Model, job.TaskID
	}
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	fmt.Fprintf(w, "# HELP ai_eval_stress_qps 当前 QPS\n# TYPE ai_eval_stress_qps gauge\n")
	fmt.Fprintf(w, "ai_eval_stress_qps{env=%q,model=%q,task_id=%q} %f\n", env, model, taskID, snap.QPS)
	fmt.Fprintf(w, "# HELP ai_eval_stress_rt_ms 平均响应时间\n# TYPE ai_eval_stress_rt_ms gauge\n")
	fmt.Fprintf(w, "ai_eval_stress_rt_ms{env=%q,model=%q,task_id=%q} %f\n", env, model, taskID, snap.RTMs)
	fmt.Fprintf(w, "# HELP ai_eval_stress_error_rate 错误率(0-1)\n# TYPE ai_eval_stress_error_rate gauge\n")
	fmt.Fprintf(w, "ai_eval_stress_error_rate{env=%q,model=%q,task_id=%q} %f\n", env, model, taskID, snap.ErrorRate)
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
	if job.TaskID == "" || job.URL == "" {
		http.Error(w, "task_id and url required", http.StatusBadRequest)
		return
	}
	if job.QPS < 1 {
		job.QPS = 1
	}
	if job.QPS > 1000 {
		job.QPS = 1000
	}
	if job.DurationS < 1 {
		job.DurationS = 1
	}
	if job.DurationS > 1800 {
		job.DurationS = 1800
	}
	if job.Method == "" {
		if len(job.Body) > 0 {
			job.Method = http.MethodPost
		} else {
			job.Method = http.MethodGet
		}
	}

	ctx, cancel := context.WithCancel(context.Background())
	runner := &runningJob{
		job:       job,
		cancel:    cancel,
		status:    "running",
		latencies: make([]float64, 0, 1024),
		started:   time.Now().UTC(),
	}

	jobsMu.Lock()
	if existing, ok := jobs[job.TaskID]; ok && existing.getStatus() == "running" {
		jobsMu.Unlock()
		cancel()
		http.Error(w, "job already running", http.StatusConflict)
		return
	}
	jobs[job.TaskID] = runner
	jobsMu.Unlock()

	log.Printf("stress job start task=%s env=%s model=%s qps=%d duration=%ds",
		job.TaskID, job.Env, job.Model, job.QPS, job.DurationS)
	go runner.loop(ctx)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted)
	_ = json.NewEncoder(w).Encode(map[string]any{"status": "accepted", "task_id": job.TaskID})
}

func handleStatus(w http.ResponseWriter, r *http.Request) {
	taskID := r.URL.Query().Get("task_id")
	if taskID == "" {
		http.Error(w, "task_id required", http.StatusBadRequest)
		return
	}
	jobsMu.Lock()
	runner := jobs[taskID]
	jobsMu.Unlock()
	if runner == nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(runner.snapshot())
}

func handleStop(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var body struct {
		TaskID string `json:"task_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.TaskID == "" {
		http.Error(w, "task_id required", http.StatusBadRequest)
		return
	}
	jobsMu.Lock()
	runner := jobs[body.TaskID]
	jobsMu.Unlock()
	if runner != nil {
		runner.cancel()
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"status": "stopping", "task_id": body.TaskID})
}

func (j *runningJob) getStatus() string {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.status
}

func (j *runningJob) loop(ctx context.Context) {
	defer func() {
		j.mu.Lock()
		if j.status == "running" {
			j.status = "done"
		}
		j.finished = time.Now().UTC()
		j.flushWindowLocked()
		j.mu.Unlock()
		log.Printf("stress job end task=%s status=%s", j.job.TaskID, j.getStatus())
	}()

	qps := j.job.QPS
	interval := time.Second / time.Duration(qps)
	if interval < time.Millisecond {
		interval = time.Millisecond
	}
	semCap := qps * 2
	if semCap < 4 {
		semCap = 4
	}
	if semCap > 256 {
		semCap = 256
	}
	sem := make(chan struct{}, semCap)
	client := &http.Client{Timeout: 30 * time.Second}

	ticker := time.NewTicker(interval)
	second := time.NewTicker(time.Second)
	deadline := time.NewTimer(time.Duration(j.job.DurationS) * time.Second)
	defer ticker.Stop()
	defer second.Stop()
	defer deadline.Stop()

	var wg sync.WaitGroup
	stopLaunch := false
	for !stopLaunch {
		select {
		case <-ctx.Done():
			j.mu.Lock()
			j.status = "stopped"
			j.mu.Unlock()
			stopLaunch = true
		case <-deadline.C:
			stopLaunch = true
		case <-second.C:
			j.mu.Lock()
			j.flushWindowLocked()
			j.mu.Unlock()
		case <-ticker.C:
			sem <- struct{}{}
			wg.Add(1)
			go func() {
				defer wg.Done()
				defer func() { <-sem }()
				j.fire(ctx, client)
			}()
		}
	}
	wg.Wait()
}

func (j *runningJob) fire(ctx context.Context, client *http.Client) {
	method := j.job.Method
	var reader io.Reader
	if len(j.job.Body) > 0 {
		reader = bytes.NewReader(j.job.Body)
	}
	req, err := http.NewRequestWithContext(ctx, method, j.job.URL, reader)
	if err != nil {
		j.record(false, 0)
		return
	}
	for key, value := range j.job.Headers {
		req.Header.Set(key, value)
	}
	if reader != nil && req.Header.Get("Content-Type") == "" {
		req.Header.Set("Content-Type", "application/json")
	}
	started := time.Now()
	resp, err := client.Do(req)
	latency := float64(time.Since(started).Milliseconds())
	if err != nil {
		j.record(false, latency)
		return
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	_ = resp.Body.Close()
	j.record(resp.StatusCode >= 200 && resp.StatusCode < 400, latency)
}

func (j *runningJob) record(ok bool, latencyMs float64) {
	j.mu.Lock()
	defer j.mu.Unlock()
	if ok {
		j.ok++
		j.windowOK++
	} else {
		j.err++
		j.windowErr++
	}
	if latencyMs < 0 {
		latencyMs = 0
	}
	if len(j.latencies) < 20000 {
		j.latencies = append(j.latencies, latencyMs)
	}
	j.windowLat = append(j.windowLat, latencyMs)
}

func (j *runningJob) flushWindowLocked() {
	total := j.windowOK + j.windowErr
	if total == 0 && len(j.series) > 0 {
		return
	}
	avg := mean(j.windowLat)
	errRate := 0.0
	if total > 0 {
		errRate = float64(j.windowErr) / float64(total)
	}
	j.series = append(j.series, seriesPoint{
		TS:        time.Now().UTC().Format(time.RFC3339),
		QPS:       float64(total),
		RTMs:      avg,
		ErrorRate: errRate,
	})
	j.windowOK = 0
	j.windowErr = 0
	j.windowLat = j.windowLat[:0]
}

func (j *runningJob) snapshot() jobSnapshot {
	j.mu.Lock()
	defer j.mu.Unlock()
	total := j.ok + j.err
	avg := mean(j.latencies)
	p99 := percentile(j.latencies, 0.99)
	errRate := 0.0
	if total > 0 {
		errRate = float64(j.err) / float64(total)
	}
	elapsed := time.Since(j.started).Seconds()
	if elapsed < 1 {
		elapsed = 1
	}
	achieved := float64(total) / elapsed
	var sla *bool
	if j.job.SLAP99Ms != nil {
		met := p99 <= float64(*j.job.SLAP99Ms)
		sla = &met
	}
	series := append([]seriesPoint(nil), j.series...)
	return jobSnapshot{
		Status:     j.status,
		TaskID:     j.job.TaskID,
		QPS:        achieved,
		RTMs:       avg,
		P99Ms:      p99,
		ErrorRate:  errRate,
		TimeSeries: series,
		SLAMet:     sla,
		Total:      total,
		Errors:     j.err,
	}
}

func latestSnapshot() (jobSnapshot, *StressJob) {
	jobsMu.Lock()
	defer jobsMu.Unlock()
	var latest *runningJob
	for _, runner := range jobs {
		if latest == nil || runner.started.After(latest.started) {
			latest = runner
		}
	}
	if latest == nil {
		return jobSnapshot{Status: "idle"}, nil
	}
	job := latest.job
	return latest.snapshot(), &job
}

func mean(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	sum := 0.0
	for _, value := range values {
		sum += value
	}
	return sum / float64(len(values))
}

func percentile(values []float64, p float64) float64 {
	if len(values) == 0 {
		return 0
	}
	cp := append([]float64(nil), values...)
	sort.Float64s(cp)
	idx := int(float64(len(cp)-1) * p)
	if idx < 0 {
		idx = 0
	}
	if idx >= len(cp) {
		idx = len(cp) - 1
	}
	return cp[idx]
}
