class AddRunIdToCompanies < ActiveRecord::Migration[8.1]
  def change
    add_reference :companies, :run, null: true, foreign_key: true
  end
end
