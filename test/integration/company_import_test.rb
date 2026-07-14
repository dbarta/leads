require "test_helper"

class CompanyImportTest < ActionDispatch::IntegrationTest
  FIXTURE_CSV = Rails.root.join("test/fixtures/files/sample_companies.csv")

  setup do
    # Ensure ORD and MDW airports exist for multi-airport test row
    Airport.find_or_create_by!(faa_code: "ORD") do |a|
      a.name = "Chicago O&#39;Hare Intl"; a.facility_type = "A"; a.discovery_status = "not_started"
    end
    Airport.find_or_create_by!(faa_code: "MDW") do |a|
      a.name = "Chicago Midway Intl"; a.facility_type = "A"; a.discovery_status = "not_started"
    end
  end

  test "imports companies from CSV" do
    before_companies = Company.count
    before_rels      = AirportCompanyRelationship.count

    importer = CompanyImporter.new(file: FIXTURE_CSV)
    importer.import!

    assert importer.created_count >= 1, "should create at least one company"
    assert_equal 0, importer.errors.size, "should have no errors: #{importer.errors.inspect}"
  end

  test "correctly qualifies companies" do
    CompanyImporter.new(file: FIXTURE_CSV).import!

    sample = Company.find_by(canonical_name: "Sample Ground LLC")
    assert_not_nil sample
    assert_equal "Yes", sample.qualification_status

    airline = Company.find_by(canonical_name: "Big Air Inc")
    assert_not_nil airline
    assert_equal "No", airline.qualification_status
    assert airline.is_airline?
  end

  test "creates multiple relationships for multi-airport row" do
    CompanyImporter.new(file: FIXTURE_CSV).import!

    multi = Company.find_by(canonical_name: "Multi Airport LLC")
    assert_not_nil multi
    assert_equal 2, multi.airport_company_relationships.count
    codes = multi.airports.pluck(:faa_code).sort
    assert_includes codes, "ORD"
    assert_includes codes, "MDW"
  end

  test "import is idempotent" do
    CompanyImporter.new(file: FIXTURE_CSV).import!
    before = Company.count

    importer2 = CompanyImporter.new(file: FIXTURE_CSV)
    importer2.import!

    assert_equal before, Company.count, "second import should not create duplicates"
    assert_equal 0, importer2.created_count
    assert_equal 0, importer2.relationship_count
  end
end
