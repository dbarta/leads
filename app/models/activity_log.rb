class ActivityLog < ApplicationRecord
  belongs_to :airport, optional: true
  belongs_to :discovery_run, optional: true

  validates :occurred_at, presence: true
  validates :actor_type, presence: true
  validates :action_name, presence: true

  scope :recent, -> { order(occurred_at: :desc) }
  scope :failures, -> { where(status: "failed") }
  scope :for_airport, ->(airport) { where(airport: airport) if airport.present? }
  scope :for_action, ->(action) { where(action_name: action) if action.present? }
  scope :for_status, ->(status) { where(status: status) if status.present? }
  scope :for_actor, ->(actor) { where(actor_type: actor) if actor.present? }
  scope :for_discovery_run, ->(run) { where(discovery_run: run) if run.present? }
  scope :since, ->(date) { where("occurred_at >= ?", date) if date.present? }
  scope :until_date, ->(date) { where("occurred_at <= ?", date) if date.present? }

  def self.log(actor_type:, action_name:, summary: nil, status: "success",
    airport: nil, discovery_run: nil, record: nil, details: {}, error_message: nil,
    duration_ms: nil)
    create!(
      occurred_at: Time.current,
      actor_type: actor_type,
      action_name: action_name,
      summary: summary,
      status: status,
      airport: airport,
      discovery_run: discovery_run,
      record_type: record&.class&.name,
      record_id: record.respond_to?(:id) ? record.id : nil,
      details: details,
      error_message: error_message,
      duration_ms: duration_ms
    )
  end

  def success?
    status == "success"
  end

  def failed?
    status == "failed"
  end
end
