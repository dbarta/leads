class Source < ApplicationRecord
  SOURCE_TYPES = %w[faa_airport_dataset certified_provider_roster permitted_provider_roster
    service_provider_contact_list tenant_directory cargo_directory fbo_directory
    airport_contract procurement_record board_minutes planning_document
    airport_webpage government_record manual_source].freeze

  PROCESSING_STATUSES = %w[pending processing completed failed skipped].freeze

  belongs_to :airport, optional: true

  validates :source_type, presence: true, inclusion: {in: SOURCE_TYPES}
  validates :processing_status, inclusion: {in: PROCESSING_STATUSES}

  scope :for_airport, ->(airport) { where(airport: airport) }
  scope :by_type, ->(type) { where(source_type: type) if type.present? }
  scope :by_status, ->(status) { where(processing_status: status) if status.present? }
end
