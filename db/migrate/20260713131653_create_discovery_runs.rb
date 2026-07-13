class CreateDiscoveryRuns < ActiveRecord::Migration[8.1]
  def change
    create_table :discovery_runs do |t|
      t.references :airport, null: false, foreign_key: true
      t.datetime :started_at
      t.datetime :completed_at
      t.string :status, null: false, default: "not_started"
      t.string :discovery_method
      t.integer :sources_checked, null: false, default: 0
      t.integer :sources_found, null: false, default: 0
      t.integer :companies_found, null: false, default: 0
      t.integer :companies_created, null: false, default: 0
      t.integer :relationships_created, null: false, default: 0
      t.integer :possible_duplicates_found, null: false, default: 0
      t.text :error_details
      t.text :summary

      t.timestamps
    end

    add_index :discovery_runs, :status
    add_index :discovery_runs, :started_at
  end
end
