require "test_helper"

class FaaImportTest < ActionDispatch::IntegrationTest
  FIXTURE_CSV = Rails.root.join("test/fixtures/files/sample_apt.csv").to_s

  test "imports airports from local CSV file" do
    assert_difference "Airport.count", 2 do
      run_import
    end

    sfo = Airport.find_by(faa_code: "SFO")
    assert_not_nil sfo
    assert_equal "SAN FRANCISCO INTL", sfo.name
    assert_equal "CA", sfo.state
    assert_equal "KSFO", sfo.icao_code
    assert_in_delta 37.6189722, sfo.latitude.to_f, 0.001
    assert_equal "not_started", sfo.discovery_status
    assert_not_nil sfo.last_imported_at
  end

  test "import is idempotent — re-running does not create duplicates" do
    run_import
    count_after_first = Airport.count

    run_import
    assert_equal count_after_first, Airport.count
  end

  test "import updates last_imported_at on re-run" do
    run_import
    jfk = Airport.find_by(faa_code: "JFK")
    original_imported_at = jfk.last_imported_at

    travel 5.seconds do
      run_import
      jfk.reload
      assert jfk.last_imported_at > original_imported_at
    end
  end

  test "import ensures exactly one FAA dataset Source exists after multiple runs" do
    run_import
    count_after_first = Source.where(source_type: "faa_airport_dataset").count

    run_import
    assert_equal count_after_first, Source.where(source_type: "faa_airport_dataset").count
  end

  test "importer reports created and updated counts" do
    importer = run_import
    assert_equal 2, importer.created_count
    assert_equal 0, importer.updated_count

    importer2 = run_import
    assert_equal 0, importer2.created_count
    assert_equal 2, importer2.updated_count
  end

  private

  def run_import
    importer = FaaAirportImporter.new(file: FIXTURE_CSV)
    importer.import!
    importer
  end
end
