class ContactsController < ApplicationController
  before_action :authenticate_user!

  SORTABLE_COLUMNS = %w[last_name title source company_name airports naics employee_max].freeze

  def index
    @contacts = filtered_contacts
    @contacts = apply_sort(@contacts)
    @pagy, @contacts = pagy(@contacts, limit: 100)
    @total_contacts = Contact.count
  end

  def export
    require "csv"
    contacts = apply_sort(filtered_contacts)
      .includes(company: [:airports, :airport_company_relationships])

    csv_data = CSV.generate(headers: true) do |csv|
      csv << %w[id full_name title email phone linkedin_url source
                company_id company_name company_phone qualification_status airports]
      contacts.each do |c|
        csv << [
          c.id,
          c.full_name,
          c.title,
          c.email,
          c.phone,
          c.linkedin_url,
          c.source,
          c.company_id,
          c.company&.canonical_name,
          c.company&.phone,
          c.company&.qualification_status,
          c.company&.airports&.map(&:faa_code)&.sort&.join("; "),
        ]
      end
    end

    send_data csv_data,
      filename: "contacts_#{Date.today}.csv",
      type: "text/csv",
      disposition: "attachment"
  end

  private

  def filtered_contacts
    scope = Contact.includes(company: [:airports]).joins("LEFT JOIN companies ON companies.id = contacts.company_id")
    scope = scope.where("contacts.full_name ILIKE ? OR contacts.title ILIKE ? OR contacts.email ILIKE ?",
                        "%#{params[:q]}%", "%#{params[:q]}%", "%#{params[:q]}%") if params[:q].present?
    scope = scope.with_email    if params[:has_email] == "1"
    scope = scope.with_phone    if params[:has_phone] == "1"
    scope = scope.by_source(params[:source])
    if params[:qualification].present?
      scope = scope.where(companies: {qualification_status: params[:qualification]})
    end
    scope = scope.where("COALESCE(companies.employee_max, companies.employee_min) <= ?", params[:emp_max].to_i) if params[:emp_max].present?
    scope = scope.where("COALESCE(companies.employee_min, companies.employee_max) >= ?", params[:emp_min].to_i) if params[:emp_min].present?
    if params[:hide_airlines_banks] == "1"
      scope = scope.where(companies: {is_airline: false})
                   .where("(companies.naics_codes NOT ILIKE '522%' OR companies.naics_codes IS NULL)")
                   .where("companies.canonical_name NOT ILIKE '%bank%'")
    end
    scope
  end

  def apply_sort(scope)
    col = SORTABLE_COLUMNS.include?(params[:sort]) ? params[:sort] : "last_name"
    dir = params[:direction] == "desc" ? "DESC" : "ASC"
    order_sql = case col
    when "company_name"
      "companies.canonical_name #{dir} NULLS LAST"
    when "airports"
      # Sort on first airport FAA code via subquery
      <<~SQL
        (SELECT MIN(a.faa_code) FROM airports a
         INNER JOIN airport_company_relationships acr ON acr.airport_id = a.id
         WHERE acr.company_id = companies.id) #{dir} NULLS LAST
      SQL
    when "naics"
      "companies.naics_codes #{dir} NULLS LAST"
    when "employee_max"
      "COALESCE(companies.employee_max, companies.employee_min) #{dir} NULLS LAST"
    else
      "contacts.#{col} #{dir} NULLS LAST"
    end
    scope.order(Arel.sql(order_sql))
  end
end
