class Airport < ApplicationRecord
  DISCOVERY_STATUSES = %w[not_started queued running completed completed_no_sources
    completed_no_providers needs_review failed].freeze

  FACILITY_TYPE_LABELS = {
    "A" => "Airport",
    "B" => "Balloonport",
    "C" => "Seaplane Base",
    "G" => "Gliderport",
    "H" => "Heliport",
    "S" => "Stolport",
    "U" => "Ultralight"
  }.freeze

  has_many :sources, dependent: :destroy
  has_many :discovery_runs, dependent: :destroy
  has_many :activity_logs, dependent: :destroy
  has_many :airport_company_relationships, dependent: :destroy
  has_many :companies, through: :airport_company_relationships

  validates :faa_code, presence: true, uniqueness: {case_sensitive: false}
  validates :name, presence: true
  validates :discovery_status, inclusion: {in: DISCOVERY_STATUSES}, allow_blank: true

  before_save { faa_code&.upcase! }

  scope :by_state, ->(state) { where(state: state) if state.present? }
  scope :by_facility_type, ->(type) { where(facility_type: type) if type.present? }
  scope :by_discovery_status, ->(status) { where(discovery_status: status) if status.present? }
  scope :commercial_only, -> { where.not(far_139_type_code: [nil, ""]) }
  scope :by_size, ->(size) {
    prefix = {"Large" => "I", "Medium" => "II", "Small" => "III", "Tiny" => "IV"}[size]
    where("far_139_type_code LIKE ?", "#{prefix} %") if prefix
  }
  scope :public_use_only, -> { where(public_use: true) }
  scope :search_text, ->(q) {
    where("name ILIKE :q OR faa_code ILIKE :q OR icao_code ILIKE :q OR iata_code ILIKE :q OR city ILIKE :q", q: "%#{sanitize_sql_like(q)}%") if q.present?
  }

  def commercial?
    far_139_type_code.present?
  end

  def hub_size
    return nil if far_139_type_code.blank?
    case far_139_type_code.split(" ").first
    when "I"   then "Large"
    when "II"  then "Medium"
    when "III" then "Small"
    when "IV"  then "Tiny"
    end
  end

  def display_name
    "#{name} (#{faa_code})"
  end

  def discovery_pending?
    discovery_status == "not_started"
  end
end
