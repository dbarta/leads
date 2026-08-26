class Run < ApplicationRecord
  has_many :contacts

  validates :name, presence: true

  def airports_list
    airports.to_s.split(",").map(&:strip).reject(&:blank?)
  end

  def contact_count
    contacts.count
  end

  def duration
    return nil unless started_at && completed_at
    ((completed_at - started_at) / 1.day).round
  end
end
