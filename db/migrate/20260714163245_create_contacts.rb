class CreateContacts < ActiveRecord::Migration[8.1]
  def change
    create_table :contacts do |t|
      t.references :company, null: false, foreign_key: true
      t.string :full_name, null: false
      t.string :first_name
      t.string :last_name
      t.string :title
      t.string :email
      t.string :phone
      t.string :linkedin_url
      t.string :source   # "apollo", "pdl", "both"
      t.text   :notes
      t.timestamps
    end

    # Dedup by email within a company; allow multiple contacts without email
    add_index :contacts, [:company_id, :email], unique: true, where: "email IS NOT NULL AND email != ''"
    add_index :contacts, :email
  end
end
