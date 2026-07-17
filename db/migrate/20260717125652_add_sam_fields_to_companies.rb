class AddSamFieldsToCompanies < ActiveRecord::Migration[8.1]
  def change
    add_column :companies, :entity_start_date,        :date
    add_column :companies, :entity_structure,          :string
    add_column :companies, :state_of_incorporation,    :string
    add_column :companies, :sam_business_types,        :text
    add_column :companies, :physical_address_line1,    :string
    add_column :companies, :physical_address_line2,    :string
    add_column :companies, :physical_address_city,     :string
    add_column :companies, :physical_address_state,    :string
    add_column :companies, :physical_address_zip,      :string
    add_column :companies, :physical_address_country,  :string
  end
end
