require "test_helper"

class ActivityLogsControllerTest < ActionDispatch::IntegrationTest
  setup do
    sign_in users(:one)
  end

  test "index responds with success" do
    get activity_logs_url
    assert_response :success
  end

  test "index shows log entries" do
    get activity_logs_url
    assert_match "FAA airport import started", response.body
    assert_match "FAA import complete", response.body
  end

  test "index filters by status" do
    get activity_logs_url, params: {status: "failed"}
    assert_response :success
    assert_match "Python parser failed", response.body
    assert_no_match "FAA import complete", response.body
  end

  test "index filters by failures_only" do
    get activity_logs_url, params: {failures_only: "1"}
    assert_response :success
    assert_match "Python parser failed", response.body
    assert_no_match "FAA import complete", response.body
  end

  test "index filters by action_name" do
    get activity_logs_url, params: {action_name: "faa_import_started"}
    assert_response :success
    assert_match "FAA airport import started", response.body
    # Failure summary should not appear in filtered results
    assert_no_match "Python parser failed", response.body
  end

  test "redirects unauthenticated users" do
    sign_out :user
    get activity_logs_url
    assert_response :redirect
  end
end
