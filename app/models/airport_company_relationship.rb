class AirportCompanyRelationship < ApplicationRecord
  belongs_to :airport
  belongs_to :company

  def service_categories_display
    service_categories.join("; ")
  end
end
