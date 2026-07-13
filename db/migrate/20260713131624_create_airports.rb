class CreateAirports < ActiveRecord::Migration[8.1]
  def change
    create_table :airports do |t|
      t.string :faa_code, null: false
      t.string :icao_code
      t.string :iata_code
      t.string :name, null: false
      t.string :facility_type
      t.string :city
      t.string :county
      t.string :state
      t.decimal :latitude, precision: 10, scale: 7
      t.decimal :longitude, precision: 10, scale: 7
      t.string :ownership_type
      t.string :owner_name
      t.string :airport_status
      t.string :source_url
      t.date :source_dataset_date
      t.datetime :last_imported_at
      t.string :discovery_status, null: false, default: "not_started"

      t.timestamps
    end

    add_index :airports, :faa_code, unique: true
    add_index :airports, :state
    add_index :airports, :discovery_status
    add_index :airports, :facility_type
  end
end
