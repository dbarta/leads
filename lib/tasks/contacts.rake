namespace :contacts do
  desc "Import contacts CSV: rake contacts:import[path/to/contacts.csv]"
  task :import, [:file] => :environment do |_, args|
    file = args[:file] or abort "Usage: rake contacts:import[path/to/contacts.csv]"
    require "csv"

    created = 0
    updated = 0
    errors  = []

    CSV.foreach(file, headers: true) do |row|
      company_id = row["company_id"].to_i
      next unless company_id > 0

      company = Company.find_by(id: company_id)
      unless company
        errors << "Company #{company_id} not found"
        next
      end

      full_name = row["full_name"].to_s.strip
      next if full_name.blank?

      email = row["email"].presence

      contact = if email.present?
        company.contacts.find_or_initialize_by(email: email)
      else
        company.contacts.find_or_initialize_by(full_name: full_name)
      end

      was_new = contact.new_record?

      contact.assign_attributes(
        full_name:    full_name,
        first_name:   row["first_name"].presence,
        last_name:    row["last_name"].presence,
        title:        row["title"].presence,
        email:        email,
        phone:        row["phone"].presence,
        linkedin_url: row["linkedin_url"].presence,
        source:       row["source"].presence,
        notes:        row["notes"].presence
      )

      if contact.save
        was_new ? created += 1 : updated += 1
      else
        errors << "#{full_name} @ #{company.canonical_name}: #{contact.errors.full_messages.join(", ")}"
      end
    end

    puts "Contacts import: #{created} created, #{updated} updated"
    errors.each { |e| puts "  ERROR: #{e}" }
  end

  desc "Export all contacts to CSV for broker cold calling"
  task export: :environment do
    require "csv"
    out = "python/output/contacts_export_#{Date.today}.csv"
    headers = %w[company_id company_name airports qualification_status
                 full_name title email phone linkedin_url source]

    CSV.open(out, "w") do |csv|
      csv << headers
      Contact
        .includes(company: [:airports])
        .order("companies.canonical_name", :last_name, :first_name)
        .each do |c|
          csv << [
            c.company_id,
            c.company.canonical_name,
            c.company.airports.map(&:faa_code).sort.join("; "),
            c.company.qualification_status,
            c.full_name,
            c.title,
            c.email,
            c.phone,
            c.linkedin_url,
            c.source
          ]
        end
    end

    puts "Exported #{Contact.count} contacts to #{out}"
  end

  desc "Export contacts with phone numbers only (broker cold-call list)"
  task export_with_phone: :environment do
    require "csv"
    out = "python/output/coldcall_#{Date.today}.csv"
    headers = %w[company_id company_name airports qualification_status
                 full_name title phone email linkedin_url source]

    CSV.open(out, "w") do |csv|
      csv << headers
      Contact
        .with_phone
        .includes(company: [:airports])
        .order("companies.canonical_name", :last_name, :first_name)
        .each do |c|
          csv << [
            c.company_id,
            c.company.canonical_name,
            c.company.airports.map(&:faa_code).sort.join("; "),
            c.company.qualification_status,
            c.full_name,
            c.title,
            c.phone,
            c.email,
            c.linkedin_url,
            c.source
          ]
        end
    end

    count = Contact.with_phone.count
    puts "Exported #{count} contacts with phone to #{out}"
  end
end
