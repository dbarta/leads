require "csv"
require "roo"

class CompanyImporter
  LAX_FILE = Rails.root.join("../../leads/LAX_airport_service_company_leads.xlsx").expand_path
  SFO_FILE = Rails.root.join("../../leads/SFO_service_providers_not_on_LAX.csv").expand_path
  ORD_FILE = Rails.root.join("../../leads/ORD_MDW_JFK_service_companies_not_on_LAX.csv").expand_path

  attr_reader :created_count, :updated_count, :relationship_count, :errors

  def initialize(file:, airport_hint: nil)
    @file         = file.to_s
    @airport_hint = airport_hint
    @created_count      = 0
    @updated_count      = 0
    @relationship_count = 0
    @errors             = []
  end

  def import!(&block)
    if @file.end_with?(".xlsx", ".xls")
      import_excel(&block)
    else
      import_csv(&block)
    end
  end

  private

  # ── Excel (LAX) ─────────────────────────────────────────────────────────────

  def import_excel
    xlsx   = Roo::Spreadsheet.open(@file)
    sheet  = xlsx.sheet("LAX Lead Research")
    rows   = sheet.to_a
    header = rows.shift
    total  = rows.size

    airport = find_airport!("LAX")

    rows.each_with_index do |row, i|
      name           = row[0].to_s.strip
      next if name.blank?

      dba            = row[1].to_s.strip.presence
      services_raw   = row[2].to_s
      website        = row[3].to_s.strip.presence
      parent         = row[4].to_s.strip.presence
      emp_text       = row[5].to_s.strip.presence
      emp_min        = row[6].is_a?(Numeric) ? row[6].to_i : nil
      emp_max        = row[7].is_a?(Numeric) ? row[7].to_i : nil
      emp_evidence   = row[8].to_s.strip.presence
      is_airline     = row[9].to_s.strip.casecmp?("yes")
      raw_qualified  = row[11].to_s.strip
      research_status = row[12].to_s.strip.presence
      notes          = row[13].to_s.strip.presence
      verified_at    = row[14].is_a?(Date) ? row[14] : nil
      source_url     = row[15].to_s.strip.presence

      qualification = parse_qualification(is_airline, emp_min, emp_max, raw_qualified)
      services      = parse_services(services_raw)

      upsert_company(
        name: name, dba: dba, website: website, parent: parent,
        emp_text: emp_text, emp_min: emp_min, emp_max: emp_max, emp_evidence: emp_evidence,
        is_airline: is_airline, qualification: qualification,
        research_status: research_status, notes: notes, verified_at: verified_at,
        airport: airport, services: services, source_url: source_url
      )

      yield(i + 1, total, @created_count, @updated_count) if block_given? && (i + 1) % 50 == 0
    rescue => e
      @errors << "Row #{i + 2}: #{e.message}"
    end
  end

  # ── CSV (SFO and ORD/MDW/JFK) ───────────────────────────────────────────────

  def import_csv
    rows  = CSV.read(@file, headers: true, encoding: "bom|utf-8")
    total = rows.size

    rows.each_with_index do |row, i|
      name = row["Legal company name"].to_s.strip
      next if name.blank?

      dba           = row["DBA"].to_s.strip.presence
      website       = row["Website"].to_s.strip.presence
      parent        = row["Ultimate parent company"].to_s.strip.presence
      emp_text      = row["Estimated consolidated employees"].to_s.strip.presence
      emp_evidence  = (row["Employee source"] || row["Employee sources / evidence"]).to_s.strip.presence
      is_airline    = row["Airline?"].to_s.strip.casecmp?("yes")
      raw_qualified = row["Qualified lead?"].to_s.strip
      notes         = row["Notes"].to_s.strip.presence
      source_url    = (row["SFO evidence source(s)"] || row["Official roster source(s)"]).to_s.strip.presence

      verified_raw  = row["Verified date"].to_s.strip
      verified_at   = parse_date(verified_raw)

      emp_min = emp_max = nil

      qualification = parse_qualification(is_airline, emp_min, emp_max, raw_qualified)

      # Airport(s): SFO always has one; ORD/MDW/JFK may have multiple
      airport_codes = if row.key?("Airport(s) serviced")
        normalize_airport_codes(row["Airport(s) serviced"])
      elsif @airport_hint
        [@airport_hint]
      else
        ["SFO"]
      end

      services_raw = (row["SFO service"] || row["Airport service categories"]).to_s
      services     = parse_services(services_raw)

      airport_codes.each do |code|
        airport = find_airport!(code)
        upsert_company(
          name: name, dba: dba, website: website, parent: parent,
          emp_text: emp_text, emp_min: nil, emp_max: nil, emp_evidence: emp_evidence,
          is_airline: is_airline, qualification: qualification,
          research_status: nil, notes: notes, verified_at: verified_at,
          airport: airport, services: services, source_url: source_url
        )
      end

      yield(i + 1, total, @created_count, @updated_count) if block_given? && (i + 1) % 50 == 0
    rescue => e
      @errors << "Row #{i + 2}: #{e.message}"
    end
  end

  # ── Shared upsert ───────────────────────────────────────────────────────────

  def upsert_company(name:, dba:, website:, parent:, emp_text:, emp_min:, emp_max:,
                     emp_evidence:, is_airline:, qualification:, research_status:, notes:,
                     verified_at:, airport:, services:, source_url:)
    normalized = Company.normalize(name)
    return if normalized.blank?

    company = Company.find_or_initialize_by(normalized_name: normalized)
    is_new  = company.new_record?

    company.canonical_name     = name if company.canonical_name.blank?
    company.dba                = dba  if company.dba.blank? && dba.present?
    company.website            = website if company.website.blank? && website.present?
    company.ultimate_parent_name = parent if company.ultimate_parent_name.blank? && parent.present?
    company.is_airline         = is_airline
    company.employee_estimate_text = emp_text if company.employee_estimate_text.blank? && emp_text.present?
    company.employee_min       = emp_min  if company.employee_min.nil? && emp_min
    company.employee_max       = emp_max  if company.employee_max.nil? && emp_max
    company.employee_evidence  = emp_evidence if company.employee_evidence.blank? && emp_evidence.present?
    company.qualification_status = qualification if company.qualification_status.blank? || qualification_rank(qualification) < qualification_rank(company.qualification_status)
    company.research_status    = research_status if company.research_status.blank? && research_status.present?
    company.notes              = notes if company.notes.blank? && notes.present?
    company.verified_at        = verified_at if company.verified_at.nil? && verified_at

    company.save!

    if is_new
      @created_count += 1
    else
      @updated_count += 1
    end

    rel = AirportCompanyRelationship.find_or_initialize_by(airport: airport, company: company)
    if rel.new_record?
      rel.service_categories = services
      rel.source_url         = source_url
      rel.active             = true
      rel.save!
      @relationship_count += 1
    end
  end

  # ── Helpers ─────────────────────────────────────────────────────────────────

  def parse_services(str)
    return [] if str.blank?
    str.split(";").map(&:strip).reject(&:blank?)
  end

  def parse_qualification(is_airline, emp_min, emp_max, raw)
    return raw if Company::QUALIFICATION_STATUSES.include?(raw)

    if is_airline
      "No"
    elsif emp_max && emp_max < 5000
      "Yes"
    elsif emp_min && emp_min >= 5000
      "No"
    else
      "Review"
    end
  end

  # Lower rank = more definitive (prefer "Yes"/"No" over "Review"/"Uncertain")
  def qualification_rank(status)
    {"Yes" => 0, "No" => 0, "Review" => 1, "Uncertain" => 2, nil => 3, "" => 3}[status] || 3
  end

  def normalize_airport_codes(str)
    str.to_s.split(",").map(&:strip).map(&:upcase).reject(&:blank?)
  end

  def find_airport!(faa_code)
    Airport.find_by!(faa_code: faa_code)
  rescue ActiveRecord::RecordNotFound
    raise "Airport not found: #{faa_code}"
  end

  def parse_date(str)
    return nil if str.blank?
    # Excel serial date (e.g. "46215") or real date string
    if str.match?(/\A\d{5}\z/)
      Date.new(1899, 12, 30) + str.to_i
    else
      Date.parse(str) rescue nil
    end
  end
end
