class AddEnrichmentFieldsToCompanies < ActiveRecord::Migration[8.1]
  def change
    add_column :companies, :naics_codes, :string
    add_column :companies, :sam_cage_code, :string
    add_column :companies, :sam_registration_status, :string
  end
end
