class BackfillIataCodeFromFaaCode < ActiveRecord::Migration[8.1]
  # For U.S. airports the FAA location identifier and IATA code are the same
  # when the FAA code is exactly 3 uppercase letters (e.g. LAX, SFO, JFK).
  def up
    execute <<~SQL
      UPDATE airports
      SET iata_code = faa_code
      WHERE (iata_code IS NULL OR iata_code = '')
        AND faa_code ~ '^[A-Z]{3}$'
    SQL
  end

  def down
    execute <<~SQL
      UPDATE airports
      SET iata_code = ''
      WHERE faa_code ~ '^[A-Z]{3}$'
    SQL
  end
end
