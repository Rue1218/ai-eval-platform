package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestRunIsDisabledAfterStressRetirement(t *testing.T) {
	// 即使旧 Worker 提交完整合法任务，也不能重新启动发压。
	jobsMu.Lock()
	before := len(jobs)
	jobsMu.Unlock()

	run := httptest.NewRecorder()
	handleRun(run, httptest.NewRequest(http.MethodPost, "/run", strings.NewReader(`{"task_id":"late-task","url":"http://example.com"}`)))
	if run.Code != http.StatusGone {
		t.Fatalf("run status = %d, want 410", run.Code)
	}
	jobsMu.Lock()
	after := len(jobs)
	jobsMu.Unlock()
	if after != before {
		t.Fatal("disabled run created a stress job")
	}
}
