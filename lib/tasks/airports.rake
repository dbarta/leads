namespace :airports do
  desc "Import U.S. airports from FAA NASR data. Optionally pass a local file: rake airports:import_faa[/path/to/file]"
  task :import_faa, [:file] => :environment do |_, args|
    require "open3"
    require "json"

    python_script = Rails.root.join("lib/faa_import/parse_nasr.py")
    file_arg      = args[:file]

    started_at = Time.current

    ActivityLog.log(
      actor_type:  "system",
      action_name: "faa_import_started",
      summary:     "FAA airport import started#{file_arg ? " (file: #{file_arg})" : ""}",
      details:     {file: file_arg, started_at: started_at.iso8601}
    )

    puts "Running FAA airport importer..."

    cmd = ["python3", python_script.to_s]
    cmd << file_arg if file_arg.present?

    stdout, stderr, status = Open3.capture3(*cmd)

    unless status.success?
      msg = "Python parser failed (exit #{status.exitstatus}): #{stderr.strip.last(500)}"
      ActivityLog.log(
        actor_type:   "system",
        action_name:  "faa_import_failed",
        summary:      msg,
        status:       "failed",
        error_message: msg
      )
      abort msg
    end

    $stderr.puts stderr unless stderr.blank?

    airports_data = JSON.parse(stdout)
    total         = airports_data.size
    puts "Parsed #{total} airport records from FAA data."

    # Upsert a single Source record representing this FAA dataset
    dataset_date = Date.today
    faa_source = Source.find_or_create_by!(
      source_type: "faa_airport_dataset",
      url:         "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/"
    ) do |s|
      s.title            = "FAA NASR Airport Subscription Data"
      s.accessed_at      = Time.current
      s.publication_date = dataset_date
      s.processing_status = "completed"
    end
    faa_source.update!(accessed_at: Time.current, publication_date: dataset_date, processing_status: "completed")

    created_count = 0
    updated_count = 0
    batch_size    = 500

    airports_data.each_slice(batch_size).with_index do |batch, idx|
      Airport.transaction do
        batch.each do |data|
          faa_code = data["faa_code"].to_s.upcase.strip
          next if faa_code.blank?

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
            new_record ? created_count += 1 : updated_count += 1
          else
            warn "Skipping #{faa_code}: #{airport.errors.full_messages.join(", ")}"
          end
        end
      end

      offset = (idx + 1) * batch_size
      puts "  Processed #{[offset, total].min}/#{total}..."
      ActivityLog.log(
        actor_type:   "system",
        action_name:  "faa_import_progress",
        summary:      "Processed #{[offset, total].min}/#{total} airports (#{created_count} new, #{updated_count} updated)",
        details:      {processed: [offset, total].min, total: total, created: created_count, updated: updated_count}
      )
    end

    duration_ms = ((Time.current - started_at) * 1000).round
    summary = "FAA import complete: #{created_count} created, #{updated_count} updated, #{total} total (#{duration_ms}ms)"
    puts summary

    ActivityLog.log(
      actor_type:   "system",
      action_name:  "faa_import_completed",
      summary:      summary,
      details:      {created: created_count, updated: updated_count, total: total, source_id: faa_source.id},
      duration_ms:  duration_ms
    )
  end
end
