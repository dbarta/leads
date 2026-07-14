class AirportsController < ApplicationController
  before_action :authenticate_user!
  before_action :set_airport, only: [:show]

  SORTABLE_COLUMNS = %w[name faa_code city state facility_type discovery_status size].freeze

  def index
    @airports = Airport.all
    @airports = @airports.commercial_only if params[:commercial_only] == "1"
    @airports = @airports.search_text(params[:q])
    @airports = @airports.by_state(params[:state])
    @airports = @airports.by_facility_type(params[:facility_type])
    @airports = @airports.by_discovery_status(params[:discovery_status])
    @airports = @airports.where(airport_status: params[:airport_status]) if params[:airport_status].present?
    @airports = @airports.by_size(params[:size]) if params[:size].present?
    @airports = apply_sort(@airports)

    @pagy, @airports = pagy(@airports, limit: 50)

    @states             = Airport.distinct.order(:state).pluck(:state).compact
    @facility_types     = Airport.distinct.order(:facility_type).pluck(:facility_type).compact
    @discovery_statuses = Airport::DISCOVERY_STATUSES
    @total_airports     = Airport.count
  end

  def show
    @recent_runs = @airport.discovery_runs.recent.limit(5)
    @sources     = @airport.sources.order(accessed_at: :desc).limit(10)
    @companies   = @airport.companies
      .includes(:airport_company_relationships)
      .order(:canonical_name)
  end

  private

  def set_airport
    @airport = Airport.find(params[:id])
  end

  def apply_sort(scope)
    col = SORTABLE_COLUMNS.include?(params[:sort]) ? params[:sort] : "name"
    dir = params[:direction] == "desc" ? "DESC" : "ASC"

    if col == "size"
      scope.order(Arel.sql(<<~SQL.squish))
        CASE
          WHEN far_139_type_code LIKE 'I %'   THEN 1
          WHEN far_139_type_code LIKE 'II %'  THEN 2
          WHEN far_139_type_code LIKE 'III %' THEN 3
          WHEN far_139_type_code LIKE 'IV %'  THEN 4
          ELSE 5
        END #{dir}
      SQL
    else
      scope.order(Arel.sql("#{col} #{dir}"))
    end
  end
end
