class ActivityLogsController < ApplicationController
  before_action :authenticate_user!

  def index
    @logs = ActivityLog.all
    @logs = @logs.for_action(params[:action_name])
    @logs = @logs.for_status(params[:status])
    @logs = @logs.for_actor(params[:actor_type])
    @logs = @logs.for_airport(Airport.find(params[:airport_id])) if params[:airport_id].present?
    @logs = @logs.for_discovery_run(DiscoveryRun.find(params[:discovery_run_id])) if params[:discovery_run_id].present?
    @logs = @logs.since(Date.parse(params[:since]).beginning_of_day) if params[:since].present?
    @logs = @logs.until_date(Date.parse(params[:until]).end_of_day) if params[:until].present?
    @logs = @logs.failures if params[:failures_only] == "1"
    @logs = @logs.recent

    @pagy, @logs = pagy(@logs, limit: 100)

    @action_names  = ActivityLog.distinct.order(:action_name).pluck(:action_name).compact
    @actor_types   = ActivityLog.distinct.order(:actor_type).pluck(:actor_type).compact
    @statuses      = ActivityLog.distinct.order(:status).pluck(:status).compact
  rescue ActiveRecord::RecordNotFound
    redirect_to activity_logs_path, alert: "Record not found."
  end
end
