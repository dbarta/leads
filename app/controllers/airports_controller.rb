class AirportsController < ApplicationController
  before_action :authenticate_user!
  before_action :set_airport, only: [:show]

  def index
    @airports = Airport.all
    @airports = @airports.commercial_only if params[:commercial_only] == "1"
    @airports = @airports.search_text(params[:q])
    @airports = @airports.by_state(params[:state])
    @airports = @airports.by_facility_type(params[:facility_type])
    @airports = @airports.by_discovery_status(params[:discovery_status])
    @airports = @airports.where(airport_status: params[:airport_status]) if params[:airport_status].present?
    @airports = @airports.order(:name)

    @pagy, @airports = pagy(@airports, limit: 50)

    @states               = Airport.distinct.order(:state).pluck(:state).compact
    @facility_types       = Airport.distinct.order(:facility_type).pluck(:facility_type).compact
    @discovery_statuses   = Airport::DISCOVERY_STATUSES
    @total_airports       = Airport.count
  end

  def show
    @recent_runs  = @airport.discovery_runs.recent.limit(5)
    @sources      = @airport.sources.order(accessed_at: :desc).limit(10)
  end

  private

  def set_airport
    @airport = Airport.find(params[:id])
  end
end
