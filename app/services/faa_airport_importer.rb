class FaaAirportImporter
  PYTHON_SCRIPT = Rails.root.join("lib/faa_import/parse_nasr.py")
  FAA_SOURCE_URL = "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/"
  BATCH_SIZE = 500

  attr_reader :created_count, :updated_count, :total

  def initialize(file: nil)
    @file = file
    @created_count = 0
    @updated_count = 0
    @total = 0
  end

  def import!
    airports_data = parse_airports!

    @total = airports_data.size
    dataset_date = Date.today

    faa_source = Source.find_or_create_by!(
      source_type: "faa_airport_dataset",
      url: FAA_SOURCE_URL
    ) do |s|
      s.title = "FAA NASR Airport Subscription Data"
      s.accessed_at = Time.current
      s.publication_date = dataset_date
      s.processing_status = "completed"
    end
    faa_source.update!(accessed_at: Time.current, publication_date: dataset_date, processing_status: "completed")

    airports_data.each_slice(BATCH_SIZE).with_index do |batch, idx|
      Airport.transaction do
        batch.each do |data|
          upsert_airport(data, dataset_date)
        end
      end

      offset = (idx + 1) * BATCH_SIZE
      yield(offset, @total, @created_count, @updated_count) if block_given?
    end

    faa_source
  end

  private

  def parse_airports!
    require "open3"
    require "json"

    cmd = ["python3", PYTHON_SCRIPT.to_s]
    cmd << @file if @file.present?

    stdout, stderr, status = Open3.capture3(*cmd)

    $stderr.puts stderr unless stderr.blank?

    unless status.success?
      raise "Python parser failed (exit #{status.exitstatus}): #{stderr.strip.last(500)}"
    end

    JSON.parse(stdout)
  end

  def upsert_airport(data, dataset_date)
    faa_code = data["faa_code"].to_s.upcase.strip
    return if faa_code.blank?

    airport = Airport.find_or_initialize_by(faa_code: faa_code)
    new_record = airport.new_record?

    airport.assign_attributes(
      name:                data["name"].to_s.strip.presence || faa_code,
      facility_type:       data["facility_type"].to_s.strip,
      city:                data["city"].to_s.strip,
      county:              data["county"].to_s.strip,
      state:               data["state"].to_s.strip,
      latitude:            data["latitude"],
      longitude:           data["longitude"],
      ownership_type:      data["ownership_type"].to_s.strip,
      owner_name:          data["owner_name"].to_s.strip,
      airport_status:      data["airport_status"].to_s.strip,
      icao_code:           data["icao_code"].to_s.strip,
      iata_code:           data["iata_code"].to_s.strip,
      source_url:          data["source_url"],
      source_dataset_date: dataset_date,
      last_imported_at:    Time.current
    )

    if airport.save
      new_record ? @created_count += 1 : @updated_count += 1
    else
      warn "Skipping #{faa_code}: #{airport.errors.full_messages.join(", ")}"
    end
  end
end
