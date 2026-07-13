require "test_helper"

class AirportTest < ActiveSupport::TestCase
  test "faa_code must be present" do
    airport = Airport.new(name: "Test Airport")
    assert_not airport.valid?
    assert_includes airport.errors[:faa_code], "can't be blank"
  end

  test "name must be present" do
    airport = Airport.new(faa_code: "TST")
    assert_not airport.valid?
    assert_includes airport.errors[:name], "can't be blank"
  end

  test "faa_code must be unique" do
    existing = airports(:lax)
    duplicate = Airport.new(faa_code: existing.faa_code, name: "Duplicate")
    assert_not duplicate.valid?
    assert_includes duplicate.errors[:faa_code], "has already been taken"
  end

  test "faa_code is uppercased before save" do
    airport = Airport.create!(faa_code: "tst", name: "Test")
    assert_equal "TST", airport.faa_code
  end

  test "search_text scope matches on name" do
    results = Airport.search_text("Los Angeles")
    assert_includes results, airports(:lax)
    assert_not_includes results, airports(:ord)
  end

  test "search_text scope matches on faa_code" do
    results = Airport.search_text("ORD")
    assert_includes results, airports(:ord)
  end

  test "by_state scope filters by state" do
    results = Airport.by_state("CA")
    assert_includes results, airports(:lax)
    assert_not_includes results, airports(:ord)
  end

  test "by_discovery_status scope filters correctly" do
    completed = Airport.by_discovery_status("completed")
    assert_includes completed, airports(:ord)
    assert_not_includes completed, airports(:lax)
  end

  test "display_name includes faa_code" do
    airport = airports(:lax)
    assert_includes airport.display_name, "LAX"
    assert_includes airport.display_name, airport.name
  end

  test "discovery_pending? when not_started" do
    assert airports(:lax).discovery_pending?
    assert_not airports(:ord).discovery_pending?
  end

  test "has many sources" do
    assert_includes airports(:lax).sources, sources(:faa_nasr)
  end

  test "has many discovery_runs" do
    assert_includes airports(:lax).discovery_runs, discovery_runs(:lax_run)
  end
end
