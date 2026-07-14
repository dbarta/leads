class CreateCompanies < ActiveRecord::Migration[8.1]
  def change
    create_table :companies do |t|
      t.string  :canonical_name,        null: false
      t.string  :normalized_name,       null: false
      t.string  :dba
      t.string  :website
      t.string  :ultimate_parent_name
      t.boolean :is_airline,            default: false, null: false
      t.integer :employee_min
      t.integer :employee_max
      t.string  :employee_estimate_text
      t.text    :employee_evidence
      t.string  :qualification_status
      t.string  :research_status
      t.text    :notes
      t.date    :verified_at

      t.timestamps
    end

    add_index :companies, :canonical_name
    add_index :companies, :normalized_name, unique: true
    add_index :companies, :qualification_status
    add_index :companies, :is_airline
  end
end
