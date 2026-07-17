class Company < ApplicationRecord
  QUALIFICATION_STATUSES = %w[Yes No Review Uncertain].freeze

  has_many :airport_company_relationships, dependent: :destroy
  has_many :airports, through: :airport_company_relationships
  has_many :contacts, dependent: :destroy

  validates :canonical_name, presence: true
  validates :normalized_name, presence: true, uniqueness: true
  validates :qualification_status, inclusion: {in: QUALIFICATION_STATUSES}, allow_blank: true

  before_validation :set_normalized_name

  # Use COALESCE so a company with only one bound set still matches range filters.
  scope :employees_max_lte, ->(n) { where("COALESCE(employee_max, employee_min) <= ?", n.to_i) if n.present? }
  scope :employees_min_gte, ->(n) { where("COALESCE(employee_min, employee_max) >= ?", n.to_i) if n.present? }
  SAM_STATUSES = %w[Active Inactive Expired].freeze

  scope :with_naics, -> { where.not(naics_codes: [nil, ""]) }
  scope :in_sam, -> { where.not(sam_cage_code: [nil, ""]) }
  scope :by_naics, ->(code) { where("naics_codes ILIKE ?", "%#{sanitize_sql_like(code)}%") if code.present? }
  scope :by_airport, ->(airport_id) {
    joins(:airport_company_relationships)
      .where(airport_company_relationships: {airport_id: airport_id}) if airport_id.present?
  }
  scope :by_qualification, ->(status) { where(qualification_status: status) if status.present? }
  scope :hide_airlines, -> { where(is_airline: false) }
  scope :non_concession, -> { where(is_concession: false) }
  scope :search_text, ->(q) {
    where("canonical_name ILIKE :q OR dba ILIKE :q", q: "%#{sanitize_sql_like(q)}%") if q.present?
  }

  def self.normalize(name)
    return "" if name.blank?
    name
      .downcase
      .gsub(/,?\s+(llc|l\.l\.c\.|inc\.?|incorporated|ltd\.?|limited|lp|llp)\s*\.?\s*$/i, "")
      .gsub(/[^a-z0-9\s]/, "")
      .squish
  end

  def airports_summary
    airports.pluck(:faa_code).sort.join(", ")
  end

  private

  def set_normalized_name
    self.normalized_name = Company.normalize(canonical_name)
  end
end
