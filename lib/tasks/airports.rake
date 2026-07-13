namespace :airports do
  desc "Import U.S. airports from FAA NASR data. Optionally pass a local file: rake airports:import_faa[/path/to/file]"
  task :import_faa, [:file] => :environment do |_, args|
    file_arg   = args[:file]
    started_at = Time.current

    ActivityLog.log(
      actor_type:  "system",
      action_name: "faa_import_started",
      summary:     "FAA airport import started#{file_arg ? " (file: #{file_arg})" : ""}",
      details:     {file: file_arg, started_at: started_at.iso8601}
    )

    puts "Running FAA airport importer..."

    importer = FaaAirportImporter.new(file: file_arg)

    begin
      faa_source = importer.import! do |processed, total, created, updated|
        puts "  Processed #{[processed, total].min}/#{total}..."
        ActivityLog.log(
          actor_type:   "system",
          action_name:  "faa_import_progress",
          summary:      "Processed #{[processed, total].min}/#{total} airports (#{created} new, #{updated} updated)",
          details:      {processed: [processed, total].min, total: total, created: created, updated: updated}
        )
      end

      duration_ms = ((Time.current - started_at) * 1000).round
      summary = "FAA import complete: #{importer.created_count} created, #{importer.updated_count} updated, #{importer.total} total (#{duration_ms}ms)"
      puts summary

      ActivityLog.log(
        actor_type:   "system",
        action_name:  "faa_import_completed",
        summary:      summary,
        details:      {created: importer.created_count, updated: importer.updated_count, total: importer.total, source_id: faa_source.id},
        duration_ms:  duration_ms
      )
    rescue => e
      msg = "FAA import failed: #{e.message}"
      ActivityLog.log(
        actor_type:    "system",
        action_name:   "faa_import_failed",
        summary:       msg,
        status:        "failed",
        error_message: e.message
      )
      abort msg
    end
  end
end
