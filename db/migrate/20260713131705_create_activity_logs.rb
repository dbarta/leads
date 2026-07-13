class CreateActivityLogs < ActiveRecord::Migration[8.1]
  def change
    create_table :activity_logs do |t|
      t.datetime :occurred_at, null: false
      t.string :actor_type, null: false
      t.string :action_name, null: false
      t.string :record_type
      t.bigint :record_id
      t.references :airport, null: true, foreign_key: true
      t.references :discovery_run, null: true, foreign_key: true
      t.string :status
      t.string :summary
      t.jsonb :details, default: {}
      t.text :error_message
      t.decimal :duration_ms

      t.timestamps
    end

    add_index :activity_logs, :occurred_at
    add_index :activity_logs, :action_name
    add_index :activity_logs, :status
  end
end
