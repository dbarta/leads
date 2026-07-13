class CreateSources < ActiveRecord::Migration[8.1]
  def change
    create_table :sources do |t|
      t.references :airport, null: true, foreign_key: true
      t.string :source_type, null: false
      t.string :title
      t.string :url
      t.string :referring_url
      t.date :publication_date
      t.datetime :accessed_at
      t.string :content_type
      t.string :original_filename
      t.string :sha256
      t.string :processing_status, null: false, default: "pending"
      t.text :notes

      t.timestamps
    end

    add_index :sources, :source_type
    add_index :sources, :processing_status
  end
end
