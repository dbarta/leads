class Contact < ApplicationRecord
  belongs_to :company

  validates :full_name, presence: true

  scope :with_phone, -> { where.not(phone: [nil, ""]) }
  scope :with_email, -> { where.not(email: [nil, ""]) }
  scope :by_source, ->(s) { where(source: s) if s.present? }

  def display_phone
    phone.presence&.gsub(/[^\d+\-\(\)\s]/, "")
  end
end
