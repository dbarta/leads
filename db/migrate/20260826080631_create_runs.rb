class CreateRuns < ActiveRecord::Migration[8.1]
  def change
    create_table :runs do |t|
      t.string :name
      t.string :airports
      t.string :naics_codes
      t.text :processes
      t.text :notes
      t.datetime :started_at
      t.datetime :completed_at

      t.timestamps
    end
  end
end
