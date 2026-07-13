require "test_helper"

class ActivityLogTest < ActiveSupport::TestCase
  test "requires occurred_at" do
    log = ActivityLog.new(actor_type: "system", action_name: "test")
    assert_not log.valid?
    assert_includes log.errors[:occurred_at], "can't be blank"
  end

  test "requires actor_type" do
    log = ActivityLog.new(occurred_at: Time.current, action_name: "test")
    assert_not log.valid?
    assert_includes log.errors[:actor_type], "can't be blank"
  end

  test "requires action_name" do
    log = ActivityLog.new(occurred_at: Time.current, actor_type: "system")
    assert_not log.valid?
    assert_includes log.errors[:action_name], "can't be blank"
  end

  test ".log creates an ActivityLog record" do
    assert_difference "ActivityLog.count", 1 do
      ActivityLog.log(
        actor_type: "system",
        action_name: "test_action",
        summary: "Test summary"
      )
    end
    log = ActivityLog.order(occurred_at: :desc).first
    assert_equal "system", log.actor_type
    assert_equal "test_action", log.action_name
    assert_equal "Test summary", log.summary
    assert_equal "success", log.status
  end

  test ".log assigns airport and record" do
    airport = airports(:lax)
    log = ActivityLog.log(
      actor_type: "system",
      action_name: "airport_updated",
      airport: airport,
      record: airport,
      status: "success"
    )
    assert_equal airport, log.airport
    assert_equal "Airport", log.record_type
    assert_equal airport.id, log.record_id
  end

  test ".log can record failure with error_message" do
    log = ActivityLog.log(
      actor_type: "system",
      action_name: "faa_import_failed",
      status: "failed",
      error_message: "FileNotFoundError"
    )
    assert log.failed?
    assert_equal "FileNotFoundError", log.error_message
  end

  test "failures scope returns only failed entries" do
    failed_logs = ActivityLog.failures
    assert_includes failed_logs, activity_logs(:import_failed)
    assert_not_includes failed_logs, activity_logs(:import_completed)
  end

  test "recent scope orders by occurred_at descending" do
    logs = ActivityLog.recent.to_a
    assert logs.first.occurred_at >= logs.last.occurred_at
  end

  test "for_action scope filters by action_name" do
    results = ActivityLog.for_action("faa_import_started")
    assert_includes results, activity_logs(:import_started)
    assert_not_includes results, activity_logs(:import_completed)
  end

  test "for_airport scope filters by airport" do
    results = ActivityLog.for_airport(airports(:lax))
    assert_includes results, activity_logs(:import_completed)
    assert_not_includes results, activity_logs(:import_started)
  end
end
