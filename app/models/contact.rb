class Contact < ApplicationRecord
  belongs_to :company

  validates :full_name, presence: true
  validates :call_status, inclusion: {in: ->(_) { CALL_STATUSES.map(&:last) }}, allow_blank: true

  CALL_STATUSES = [
    ["— not called —",            ""],
    ["Left message",              "left_message"],
    ["No answer",                 "no_answer"],
    ["No longer in service",      "no_longer_in_service"],
    ["Wrong person",              "wrong_person"],
    ["Wrong title / not decision maker", "wrong_title"],
    ["Left company",              "left_company"],
    ["Interested",                "interested"],
    ["Not interested",            "not_interested"],
    ["Callback scheduled",        "callback_scheduled"],
    ["Do not call",               "do_not_call"],
  ].freeze

  CALL_STATUS_STYLES = {
    "left_message"       => "bg-blue-100 text-blue-700",
    "no_answer"          => "bg-gray-100 text-gray-600",
    "no_longer_in_service" => "bg-red-100 text-red-700",
    "wrong_person"       => "bg-orange-100 text-orange-700",
    "wrong_title"        => "bg-yellow-100 text-yellow-700",
    "left_company"       => "bg-orange-100 text-orange-700",
    "interested"         => "bg-green-100 text-green-700",
    "not_interested"     => "bg-gray-100 text-gray-500",
    "callback_scheduled" => "bg-purple-100 text-purple-700",
    "do_not_call"        => "bg-red-100 text-red-700",
  }.freeze

  scope :with_phone, -> { where.not(phone: [nil, ""]) }
  scope :with_email, -> { where.not(email: [nil, ""]) }
  scope :by_source, ->(s) { where(source: s) if s.present? }

  def display_phone
    phone.presence&.gsub(/[^\d+\-\(\)\s]/, "")
  end
end
