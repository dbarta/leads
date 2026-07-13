require "test_helper"

class DiscoveryRunTest < ActiveSupport::TestCase
  test "belongs to airport" do
    run = discovery_runs(:lax_run)
    assert_equal airports(:lax), run.airport
  end

  test "defaults status to not_started" do
    run = DiscoveryRun.create!(airport: airports(:mdw))
    assert_equal "not_started", run.status
  end

  test "completed? returns true for completed variants" do
    run = discovery_runs(:lax_run)
    assert run.completed?
  end

  test "failed? returns true when status is failed" do
    run = DiscoveryRun.new(status: "failed")
    assert run.failed?
  end

  test "duration returns seconds between start and completion" do
    run = discovery_runs(:lax_run)
    assert_equal 300, run.duration
  end

  test "duration returns nil when not completed" do
    run = DiscoveryRun.new(airport: airports(:lax), status: "running", started_at: Time.current)
    assert_nil run.duration
  end

  test "recent scope orders by started_at desc" do
    runs = DiscoveryRun.recent.to_a
    started_ats = runs.map(&:started_at).compact
    assert_equal started_ats, started_ats.sort.reverse
  end
end
