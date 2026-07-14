require "test_helper"

class CompanyTest < ActiveSupport::TestCase
  test "normalize strips LLC suffix" do
    assert_equal "acme ground services", Company.normalize("Acme Ground Services LLC")
  end

  test "normalize strips Inc and punctuation" do
    assert_equal "acme ground services", Company.normalize("Acme Ground Services, Inc.")
  end

  test "normalize handles blank" do
    assert_equal "", Company.normalize(nil)
    assert_equal "", Company.normalize("")
  end

  test "requires canonical_name" do
    c = Company.new(normalized_name: "test")
    assert_not c.valid?
    assert c.errors[:canonical_name].any?
  end

  test "sets normalized_name automatically" do
    c = Company.new(canonical_name: "Test Corp LLC")
    c.valid?
    assert_equal "test corp", c.normalized_name
  end

  test "enforces normalized_name uniqueness" do
    c1 = Company.create!(canonical_name: "Test Corp LLC")
    c2 = Company.new(canonical_name: "Test Corp Inc")
    # Both normalize to "test corp" → uniqueness violation
    assert_not c2.valid?
    assert c2.errors[:normalized_name].any?
  end

  test "allows blank qualification_status" do
    c = Company.new(canonical_name: "No Status Co")
    assert c.valid?
  end

  test "rejects invalid qualification_status" do
    c = Company.new(canonical_name: "Bad Status Co", qualification_status: "Maybe")
    assert_not c.valid?
    assert c.errors[:qualification_status].any?
  end

  test "by_qualification scope filters correctly" do
    assert_includes Company.by_qualification("Yes"), companies(:acme_ground)
    assert_not_includes Company.by_qualification("Yes"), companies(:big_airline)
  end

  test "hide_airlines scope excludes airlines" do
    assert_not_includes Company.hide_airlines, companies(:big_airline)
    assert_includes Company.hide_airlines, companies(:acme_ground)
  end

  test "search_text scope matches on name" do
    assert_includes Company.search_text("Acme"), companies(:acme_ground)
    assert_not_includes Company.search_text("Acme"), companies(:big_airline)
  end
end
