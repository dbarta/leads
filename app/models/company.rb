class Company < ApplicationRecord
  QUALIFICATION_STATUSES = %w[Yes No Review Uncertain].freeze

  belongs_to :run, optional: true
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
  scope :by_run, ->(run_id) { where(run_id: run_id) if run_id.present? }
  scope :hide_airlines, -> { where(is_airline: false) }
  scope :non_concession, -> { where(is_concession: false) }
  scope :search_text, ->(q) {
    where("canonical_name ILIKE :q OR dba ILIKE :q", q: subsequence_pattern(q)) if q.present?
  }

  def self.normalize(name)
    return "" if name.blank?
    name
      .downcase
      .gsub(/,?\s+(llc|l\.l\.c\.|inc\.?|incorporated|ltd\.?|limited|lp|llp)\s*\.?\s*$/i, "")
      .gsub(/[^a-z0-9\s]/, "")
      .squish
  end

  NAICS_DESCRIPTIONS = {
    "112990" => "Animal Production",
    "221210" => "Natural Gas Distribution",
    "221310" => "Water Supply & Irrigation",
    "221320" => "Sewage Treatment",
    "236210" => "Industrial Building Construction",
    "236220" => "Commercial Building Construction",
    "237110" => "Water & Sewer Line Construction",
    "237310" => "Highway & Street Construction",
    "237990" => "Heavy & Civil Engineering Construction",
    "238210" => "Electrical Contractors",
    "238390" => "Building Finishing Contractors",
    "238990" => "Specialty Trade Contractors",
    "311412" => "Frozen Food Manufacturing",
    "311941" => "Sauces & Dressings Manufacturing",
    "315250" => "Cut & Sew Apparel",
    "315990" => "Apparel Manufacturing",
    "322291" => "Sanitary Paper Products",
    "325612" => "Sanitation Goods Manufacturing",
    "332216" => "Handtool Manufacturing",
    "332323" => "Architectural Metal Work",
    "332439" => "Metal Container Manufacturing",
    "332510" => "Hardware Manufacturing",
    "332999" => "Fabricated Metal Products",
    "334210" => "Telephone Apparatus Mfg",
    "336390" => "Motor Vehicle Parts Mfg",
    "337126" => "Household Furniture Mfg",
    "339112" => "Surgical & Medical Instruments",
    "339113" => "Surgical Supplies",
    "339910" => "Jewelry & Silverware",
    "339940" => "Office Supplies Mfg",
    "423120" => "Auto Parts Wholesale",
    "423390" => "Construction Material Wholesale",
    "423420" => "Office Equipment Wholesale",
    "423440" => "Commercial Equipment Wholesale",
    "423450" => "Medical Equipment Wholesale",
    "423490" => "Professional Equipment Wholesale",
    "423610" => "Electrical Equipment Wholesale",
    "423840" => "Industrial Machinery Wholesale",
    "423850" => "Industrial Paper Wholesale",
    "423860" => "Transportation Equipment Wholesale",
    "423940" => "Jewelry Wholesale",
    "423990" => "Miscellaneous Durable Goods Wholesale",
    "424120" => "Office Supplies Wholesale",
    "424210" => "Drugs & Sundries Wholesale",
    "424310" => "Dry Goods Wholesale",
    "424350" => "Farm Products Wholesale",
    "424690" => "Chemical Products Wholesale",
    "424720" => "Petroleum Products Wholesale",
    "424990" => "Miscellaneous Nondurable Goods Wholesale",
    "447190" => "Gasoline Stations",
    "455219" => "General Merchandise Stores",
    "456110" => "Pharmacies & Drug Stores",
    "458110" => "Clothing Stores",
    "458310" => "Jewelry Stores",
    "459210" => "Book Stores",
    "459410" => "Sporting Goods Stores",
    "459420" => "Hobby & Toy Stores",
    "485999" => "Ground Passenger Transportation",
    "488119" => "Other Airport Operations",
    "488190" => "Air Transportation Support",
    "488510" => "Freight Transportation Arrangement",
    "513210" => "Software Publishers",
    "517121" => "Telephone Answering Services",
    "522110" => "Commercial Banking",
    "532420" => "Office Equipment Rental & Leasing",
    "541310" => "Architectural Services",
    "541320" => "Landscape Architecture",
    "541330" => "Engineering Services",
    "541410" => "Interior Design Services",
    "541490" => "Specialized Design Services",
    "541512" => "Computer Systems Design",
    "541611" => "Management Consulting",
    "541613" => "Marketing Consulting",
    "541614" => "Logistics Consulting",
    "541618" => "Other Management Consulting",
    "541690" => "Scientific & Technical Consulting",
    "541850" => "Outdoor Advertising",
    "541990" => "Professional & Technical Services",
    "561110" => "Office Administrative Services",
    "561210" => "Facilities Support Services",
    "561320" => "Temporary Help Services",
    "561499" => "Business Support Services",
    "561612" => "Security Guards & Patrol",
    "561621" => "Security Systems Services",
    "561710" => "Pest Control Services",
    "561720" => "Janitorial Services",
    "561790" => "Building Services",
    "561910" => "Packaging & Labeling Services",
    "562998" => "Waste Management Services",
    "611430" => "Professional Development Training",
    "611699" => "Miscellaneous Schools & Instruction",
    "722310" => "Food Service Contractors",
    "722320" => "Caterers",
    "722330" => "Mobile Food Services",
    "722511" => "Full-Service Restaurants",
    "722513" => "Limited-Service Restaurants",
    "722515" => "Snack & Beverage Bars",
    "811310" => "Industrial Machinery Repair",
    "812910" => "Pet Care Services",
    "813410" => "Civic & Social Organizations",
    "813910" => "Business Associations",
  }.freeze

  def primary_naics_description
    code = naics_codes.to_s.split(",").first&.strip&.sub(/E$/, "")
    NAICS_DESCRIPTIONS[code] || code.presence
  end

  def airports_summary
    airports.pluck(:faa_code).sort.join(", ")
  end

  private

  def set_normalized_name
    self.normalized_name = Company.normalize(canonical_name)
  end
end
