namespace :companies do
  desc "Import LAX companies from Excel file"
  task :import_lax, [:file] => :environment do |_, args|
    file = args[:file] || CompanyImporter::LAX_FILE
    run_import(file, label: "LAX")
  end

  desc "Import SFO companies from CSV"
  task :import_sfo, [:file] => :environment do |_, args|
    file = args[:file] || CompanyImporter::SFO_FILE
    run_import(file, label: "SFO", airport_hint: "SFO")
  end

  desc "Import ORD/MDW/JFK companies from CSV"
  task :import_ord_mdw_jfk, [:file] => :environment do |_, args|
    file = args[:file] || CompanyImporter::ORD_FILE
    run_import(file, label: "ORD/MDW/JFK")
  end

  desc "Import all company files in order (LAX → SFO → ORD/MDW/JFK)"
  task import_all: :environment do
    Rake::Task["companies:import_lax"].invoke
    Rake::Task["companies:import_sfo"].invoke
    Rake::Task["companies:import_ord_mdw_jfk"].invoke
  end

  desc "Import a crawled CSV (output from airport_crawler.py): rake companies:import_csv[path/to/file.csv]"
  task :import_csv, [:file] => :environment do |_, args|
    file = args[:file] or abort "Usage: rake companies:import_csv[path/to/file.csv]"
    label = File.basename(file, ".*")
    run_import(file, label: label)
  end

  desc "Import enrichment CSV from enrich_companies.py: rake companies:import_enrichment[path/to/enrichment.csv]"
  task :import_enrichment, [:file] => :environment do |_, args|
    file = args[:file] or abort "Usage: rake companies:import_enrichment[path/to/enrichment.csv]"
    require "csv"

    updated = 0
    skipped = 0
    errors  = []

    CSV.foreach(file, headers: true) do |row|
      id = row["id"].to_i
      next unless id > 0

      company = Company.find_by(id: id)
      unless company
        errors << "ID #{id} not found"
        next
      end

      attrs = {}
      attrs[:naics_codes] = row["naics_codes"].presence
      attrs[:sam_cage_code] = row["sam_cage_code"].presence
      attrs[:sam_registration_status] = row["sam_registration_status"].presence

      # Employee data — only update if not already set
      if company.employee_min.blank?
        if row["employee_min"].present? && row["employee_min"] =~ /\A\d+\z/
          attrs[:employee_min] = row["employee_min"].to_i
        end
        if row["employee_max"].present? && row["employee_max"] =~ /\A\d+\z/
          attrs[:employee_max] = row["employee_max"].to_i
        end
        if row["employee_estimate_text"].present?
          attrs[:employee_estimate_text] = row["employee_estimate_text"]
        end
        if row["employee_evidence"].present?
          attrs[:employee_evidence] = [company.employee_evidence, row["employee_evidence"]].compact.reject(&:empty?).join(" | ")
        end
      end

      # Website — fill in if missing
      if row["website"].present? && company.website.blank?
        attrs[:website] = row["website"]
      end

      # License info — append to notes
      if row["license_info"].present?
        attrs[:notes] = [company.notes, "License: #{row['license_info']}"].compact.reject(&:empty?).join("\n")
      end

      # OpenCorporates — append dissolution notice to notes
      if row["opencorp_status"].present? &&
          row["opencorp_status"].downcase.in?(%w[dissolved inactive revoked])
        note = "OpenCorporates: #{row['opencorp_status']}" +
               (row["opencorp_jurisdiction"].present? ? " (#{row['opencorp_jurisdiction']})" : "")
        attrs[:notes] = [attrs[:notes] || company.notes, note].compact.reject(&:empty?).join("\n")
      end

      # People Data Labs — employee count + size range + NAICS
      if company.employee_min.blank?
        if row["pdl_employee_count"].present? && row["pdl_employee_count"] =~ /\A\d+\z/
          pdl_count = row["pdl_employee_count"].to_i
          if pdl_count > 0
            attrs[:employee_min] = pdl_count
            attrs[:employee_max] = pdl_count
            attrs[:employee_estimate_text] ||= pdl_count.to_s
            attrs[:employee_evidence] = [company.employee_evidence, "People Data Labs: #{pdl_count} employees"].compact.reject(&:empty?).join(" | ")
          end
        elsif row["pdl_size"].present?
          attrs[:employee_estimate_text] ||= row["pdl_size"]
          attrs[:employee_evidence] = [company.employee_evidence, "People Data Labs: #{row['pdl_size']} (size range)"].compact.reject(&:empty?).join(" | ")
        end
      end
      if row["pdl_naics"].present? && attrs[:naics_codes].blank? && company.naics_codes.blank?
        attrs[:naics_codes] = row["pdl_naics"]
      end

      # FMCSA — driver count as employee estimate when nothing else available
      if company.employee_min.blank? && row["fmcsa_drivers"].present? && row["fmcsa_drivers"] =~ /\A\d+\z/
        drivers = row["fmcsa_drivers"].to_i
        if drivers > 0
          attrs[:employee_min] ||= drivers
          attrs[:employee_max] ||= drivers
          fmcsa_note = "FMCSA SAFER: #{drivers} drivers" +
                       (row["fmcsa_power_units"].present? ? " / #{row['fmcsa_power_units']} power units" : "") +
                       (row["fmcsa_dot"].present? ? " (DOT ##{row['fmcsa_dot']})" : "")
          attrs[:employee_evidence] = [company.employee_evidence, fmcsa_note].compact.reject(&:empty?).join(" | ")
          attrs[:employee_estimate_text] ||= drivers.to_s
        end
      end

      attrs.compact!
      if attrs.any?
        company.update!(attrs)
        updated += 1
      else
        skipped += 1
      end
    end

    puts "Enrichment import done: #{updated} updated, #{skipped} skipped"
    errors.each { |e| puts "  ERROR: #{e}" }
  end

  desc "Export companies to CSV for enrichment script"
  task export_for_enrichment: :environment do
    require "csv"
    out = "python/companies_for_enrichment.csv"
    CSV.open(out, "w", headers: true) do |csv|
      csv << %w[id canonical_name normalized_name website airport_codes service_categories
                employee_min employee_max naics_codes sam_cage_code qualification_status]
      Company.includes(:airports, :airport_company_relationships).order(:id).each do |c|
        csv << [
          c.id, c.canonical_name, c.normalized_name, c.website,
          c.airports.map(&:faa_code).join("; "),
          c.airport_company_relationships.flat_map(&:service_categories).uniq.reject(&:empty?).join("; "),
          c.employee_min, c.employee_max, c.naics_codes, c.sam_cage_code, c.qualification_status
        ]
      end
    end
    puts "Exported #{Company.count} companies to #{out}"
  end

  def run_import(file, label:, airport_hint: nil)
    puts "Importing #{label} from #{file}…"

    ActivityLog.log(
      actor_type: "system", action_name: "company_import_started",
      summary: "#{label} company import started",
      details: {file: file.to_s, label: label}
    )

    importer = CompanyImporter.new(file: file, airport_hint: airport_hint)

    begin
      importer.import! do |processed, total, created, updated|
        puts "  #{processed}/#{total} — #{created} created, #{updated} updated"
        ActivityLog.log(
          actor_type: "system", action_name: "company_import_progress",
          summary: "#{label} import progress: #{processed}/#{total}",
          details: {processed: processed, total: total, created: created, updated: updated}
        )
      end

      puts "Done: #{importer.created_count} created, #{importer.updated_count} updated, " \
           "#{importer.relationship_count} relationships"
      importer.errors.each { |e| puts "  ERROR: #{e}" }

      ActivityLog.log(
        actor_type: "system", action_name: "company_import_completed",
        summary: "#{label} import completed: #{importer.created_count} created, #{importer.updated_count} updated",
        details: {
          label: label,
          created: importer.created_count,
          updated: importer.updated_count,
          relationships: importer.relationship_count,
          errors: importer.errors
        }
      )
    rescue => e
      puts "FAILED: #{e.message}"
      ActivityLog.log(
        actor_type: "system", action_name: "company_import_failed",
        status: "failed", error_message: e.message,
        summary: "#{label} import failed: #{e.message}",
        details: {label: label, file: file.to_s}
      )
      raise
    end
  end
end
