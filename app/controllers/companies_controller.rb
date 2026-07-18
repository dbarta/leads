class CompaniesController < ApplicationController
  before_action :authenticate_user!
  before_action :set_company, only: [:show]

  SORTABLE_COLUMNS = %w[canonical_name qualification_status employee_max is_airline].freeze

  def index
    @companies = filtered_companies
    @companies = apply_sort(@companies)

    @pagy, @companies = pagy(@companies, limit: 50)

    @top_contacts = top_contacts_for(@companies.map(&:id))
    @airports_with_companies = Airport.joins(:companies).distinct.order(:name)
    @total_companies         = Company.count
  end

  def export
    require "csv"
    companies = apply_sort(filtered_companies)
    contacts  = top_contacts_for(companies.map(&:id))

    csv_data = CSV.generate(headers: true) do |csv|
      csv << %w[id name dba airports services employees phone
                qualification contact_name contact_title contact_phone contact_email]
      companies.includes(:airports, :airport_company_relationships).each do |c|
        contact = contacts[c.id]
        rels    = c.airport_company_relationships
        csv << [
          c.id,
          c.canonical_name,
          c.dba,
          c.airports.map(&:faa_code).sort.join("; "),
          rels.flat_map(&:service_categories).uniq.reject(&:empty?).join("; "),
          [c.employee_min, c.employee_max].compact.join("–"),
          c.phone,
          c.qualification_status,
          contact&.full_name,
          contact&.title,
          contact&.phone,
          contact&.email,
        ]
      end
    end

    filename = "companies_#{Date.today}.csv"
    send_data csv_data, filename: filename, type: "text/csv", disposition: "attachment"
  end

  def show
    @relationships = @company.airport_company_relationships
      .includes(:airport)
      .order("airports.name")
    @contacts = @company.contacts.order(:last_name, :first_name)
  end

  private

  def set_company
    @company = Company.find(params[:id])
  end

  def filtered_companies
    scope = Company.all
    scope = scope.by_airport(params[:airport_id])          if params[:airport_id].present?
    scope = scope.by_qualification(params[:qualification_status])
    scope = scope.hide_airlines                            if params[:hide_airlines] == "1"
    scope = scope.non_concession                          if params[:hide_concessions] == "1"
    scope = scope.employees_max_lte(params[:emp_max])
    scope = scope.employees_min_gte(params[:emp_min])
    scope = scope.search_text(params[:q])
    scope = scope.by_naics(params[:naics])
    scope = scope.in_sam                                   if params[:in_sam] == "1"
    scope
  end

  def apply_sort(scope)
    col = SORTABLE_COLUMNS.include?(params[:sort]) ? params[:sort] : "canonical_name"
    dir = params[:direction] == "desc" ? "DESC" : "ASC"
    scope.order(Arel.sql("#{col} #{dir}"))
  end

  # Returns {company_id => best_contact} for the given IDs.
  # "Best" = lowest GL title priority (owner/CFO first).
  GL_TITLE_PRIORITY = %w[
    owner president ceo founder principal managing\ member general\ manager
    cfo controller finance\ director vp\ finance
    risk\ manager director\ of\ risk insurance\ manager
  ].freeze

  def top_contacts_for(company_ids)
    return {} if company_ids.empty?
    contacts = Contact.where(company_id: company_ids)
    contacts.group_by(&:company_id).transform_values do |list|
      list.min_by { |c| gl_priority(c.title) }
    end
  end

  def gl_priority(title)
    t = (title || "").downcase
    GL_TITLE_PRIORITY.each_with_index { |kw, i| return i if t.include?(kw) }
    999
  end
end
