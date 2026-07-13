class DiscoveryRun < ApplicationRecord
  STATUSES = %w[not_started queued running completed completed_no_sources
    completed_no_providers needs_review failed].freeze

  belongs_to :airport
  has_many :activity_logs, dependent: :nullify

  validates :status, inclusion: {in: STATUSES}

  scope :recent, -> { order(started_at: :desc) }
  scope :by_status, ->(status) { where(status: status) if status.present? }

  def duration
    return nil unless started_at && completed_at
    completed_at - started_at
  end

  def completed?
    %w[completed completed_no_sources completed_no_providers].include?(status)
  end

  def failed?
    status == "failed"
  end
end
