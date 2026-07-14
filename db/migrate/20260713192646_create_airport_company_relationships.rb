class CreateAirportCompanyRelationships < ActiveRecord::Migration[8.1]
  def change
    create_table :airport_company_relationships do |t|
      t.references :airport, null: false, foreign_key: true, index: true
      t.references :company, null: false, foreign_key: true, index: true
      t.text    :service_categories, array: true, default: []
      t.string  :source_url
      t.text    :evidence_notes
      t.boolean :active, default: true, null: false

      t.timestamps
    end

    add_index :airport_company_relationships, [:airport_id, :company_id], unique: true,
              name: "index_acr_on_airport_and_company"
  end
end
