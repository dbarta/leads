class CompaniesController < ApplicationController
  before_action :authenticate_user!
  before_action :set_company, only: [:show]

  SORTABLE_COLUMNS = %w[canonical_name qualification_status employee_max is_airline].freeze

  def index
    @companies = Company.all
    @companies = @companies.by_airport(params[:airport_id]) if params[:airport_id].present?
    @companies = @companies.by_qualification(params[:qualification_status])
    @companies = @companies.hide_airlines if params[:hide_airlines] == "1"
    @companies = @companies.employees_max_lte(params[:emp_max])
    @companies = @companies.employees_min_gte(params[:emp_min])
    @companies = @companies.search_text(params[:q])
    @companies = @companies.by_naics(params[:naics])
    @companies = @companies.in_sam if params[:in_sam] == "1"
    @companies = apply_sort(@companies)

    @pagy, @companies = pagy(@companies, limit: 50)

    @airports_with_companies = Airport.joins(:companies).distinct.order(:name)
    @total_companies         = Company.count
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

  def apply_sort(scope)
    col = SORTABLE_COLUMNS.include?(params[:sort]) ? params[:sort] : "canonical_name"
    dir = params[:direction] == "desc" ? "DESC" : "ASC"
    scope.order(Arel.sql("#{col} #{dir}"))
  end
end
