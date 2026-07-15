# This file is auto-generated from the current state of the database. Instead
# of editing this file, please use the migrations feature of Active Record to
# incrementally modify your database, and then regenerate this schema definition.
#
# This file is the source Rails uses to define your schema when running `bin/rails
# db:schema:load`. When creating a new database, `bin/rails db:schema:load` tends to
# be faster and is potentially less error prone than running all of your
# migrations from scratch. Old migrations may fail to apply correctly if those
# migrations use external dependencies or application code.
#
# It's strongly recommended that you check this file into your version control system.

ActiveRecord::Schema[8.1].define(version: 2026_07_14_195735) do
  # These are extensions that must be enabled in order to support this database
  enable_extension "pg_catalog.plpgsql"

  create_table "account_invitations", force: :cascade do |t|
    t.bigint "account_id", null: false
    t.datetime "created_at", null: false
    t.string "email", null: false
    t.bigint "invited_by_id"
    t.string "name", null: false
    t.jsonb "roles", default: {}, null: false
    t.string "token", null: false
    t.datetime "updated_at", null: false
    t.index ["account_id", "email"], name: "index_account_invitations_on_account_id_and_email", unique: true
    t.index ["invited_by_id"], name: "index_account_invitations_on_invited_by_id"
    t.index ["token"], name: "index_account_invitations_on_token", unique: true
  end

  create_table "account_users", force: :cascade do |t|
    t.bigint "account_id"
    t.datetime "created_at", null: false
    t.jsonb "roles", default: {}, null: false
    t.datetime "updated_at", null: false
    t.bigint "user_id"
    t.index ["account_id", "user_id"], name: "index_account_users_on_account_id_and_user_id", unique: true
    t.index ["account_id"], name: "index_account_users_on_account_id"
    t.index ["user_id"], name: "index_account_users_on_user_id"
  end

  create_table "accounts", force: :cascade do |t|
    t.integer "account_users_count", default: 0
    t.string "billing_email"
    t.datetime "created_at", null: false
    t.string "domain"
    t.text "extra_billing_info"
    t.string "name", null: false
    t.bigint "owner_id"
    t.boolean "personal", default: false
    t.string "subdomain"
    t.datetime "updated_at", null: false
    t.index ["owner_id"], name: "index_accounts_on_owner_id"
  end

  create_table "action_text_embeds", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.jsonb "fields"
    t.datetime "updated_at", null: false
    t.string "url"
  end

  create_table "action_text_rich_texts", force: :cascade do |t|
    t.text "body"
    t.datetime "created_at", precision: nil, null: false
    t.string "name", null: false
    t.bigint "record_id", null: false
    t.string "record_type", null: false
    t.datetime "updated_at", precision: nil, null: false
    t.index ["record_type", "record_id", "name"], name: "index_action_text_rich_texts_uniqueness", unique: true
  end

  create_table "active_storage_attachments", force: :cascade do |t|
    t.bigint "blob_id", null: false
    t.datetime "created_at", precision: nil, null: false
    t.string "name", null: false
    t.bigint "record_id", null: false
    t.string "record_type", null: false
    t.index ["blob_id"], name: "index_active_storage_attachments_on_blob_id"
    t.index ["record_type", "record_id", "name", "blob_id"], name: "index_active_storage_attachments_uniqueness", unique: true
  end

  create_table "active_storage_blobs", force: :cascade do |t|
    t.bigint "byte_size", null: false
    t.string "checksum"
    t.string "content_type"
    t.datetime "created_at", precision: nil, null: false
    t.string "filename", null: false
    t.string "key", null: false
    t.text "metadata"
    t.string "service_name", null: false
    t.index ["key"], name: "index_active_storage_blobs_on_key", unique: true
  end

  create_table "active_storage_variant_records", force: :cascade do |t|
    t.bigint "blob_id", null: false
    t.string "variation_digest", null: false
    t.index ["blob_id", "variation_digest"], name: "index_active_storage_variant_records_uniqueness", unique: true
  end

  create_table "activity_logs", force: :cascade do |t|
    t.string "action_name", null: false
    t.string "actor_type", null: false
    t.bigint "airport_id"
    t.datetime "created_at", null: false
    t.jsonb "details", default: {}
    t.bigint "discovery_run_id"
    t.decimal "duration_ms"
    t.text "error_message"
    t.datetime "occurred_at", null: false
    t.bigint "record_id"
    t.string "record_type"
    t.string "status"
    t.string "summary"
    t.datetime "updated_at", null: false
    t.index ["action_name"], name: "index_activity_logs_on_action_name"
    t.index ["airport_id"], name: "index_activity_logs_on_airport_id"
    t.index ["discovery_run_id"], name: "index_activity_logs_on_discovery_run_id"
    t.index ["occurred_at"], name: "index_activity_logs_on_occurred_at"
    t.index ["status"], name: "index_activity_logs_on_status"
  end

  create_table "airport_company_relationships", force: :cascade do |t|
    t.boolean "active", default: true, null: false
    t.bigint "airport_id", null: false
    t.bigint "company_id", null: false
    t.datetime "created_at", null: false
    t.text "evidence_notes"
    t.text "service_categories", default: [], array: true
    t.string "source_url"
    t.datetime "updated_at", null: false
    t.index ["airport_id", "company_id"], name: "index_acr_on_airport_and_company", unique: true
    t.index ["airport_id"], name: "index_airport_company_relationships_on_airport_id"
    t.index ["company_id"], name: "index_airport_company_relationships_on_company_id"
  end

  create_table "airports", force: :cascade do |t|
    t.string "airport_status"
    t.string "city"
    t.string "county"
    t.datetime "created_at", null: false
    t.string "discovery_status", default: "not_started", null: false
    t.string "faa_code", null: false
    t.string "facility_type"
    t.string "far_139_type_code"
    t.string "iata_code"
    t.string "icao_code"
    t.datetime "last_imported_at"
    t.decimal "latitude", precision: 10, scale: 7
    t.decimal "longitude", precision: 10, scale: 7
    t.string "name", null: false
    t.string "owner_name"
    t.string "ownership_type"
    t.boolean "public_use"
    t.date "source_dataset_date"
    t.string "source_url"
    t.string "state"
    t.datetime "updated_at", null: false
    t.string "website"
    t.index ["discovery_status"], name: "index_airports_on_discovery_status"
    t.index ["faa_code"], name: "index_airports_on_faa_code", unique: true
    t.index ["facility_type"], name: "index_airports_on_facility_type"
    t.index ["far_139_type_code"], name: "index_airports_on_far_139_type_code"
    t.index ["public_use"], name: "index_airports_on_public_use"
    t.index ["state"], name: "index_airports_on_state"
  end

  create_table "announcements", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.string "kind"
    t.datetime "published_at", precision: nil
    t.string "title"
    t.datetime "updated_at", null: false
  end

  create_table "api_tokens", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.datetime "expires_at", precision: nil
    t.datetime "last_used_at", precision: nil
    t.jsonb "metadata"
    t.string "name"
    t.string "token"
    t.boolean "transient", default: false
    t.datetime "updated_at", null: false
    t.bigint "user_id", null: false
    t.index ["token"], name: "index_api_tokens_on_token", unique: true
    t.index ["user_id"], name: "index_api_tokens_on_user_id"
  end

  create_table "companies", force: :cascade do |t|
    t.string "canonical_name", null: false
    t.datetime "created_at", null: false
    t.string "dba"
    t.string "employee_estimate_text"
    t.text "employee_evidence"
    t.integer "employee_max"
    t.integer "employee_min"
    t.boolean "is_airline", default: false, null: false
    t.string "naics_codes"
    t.string "normalized_name", null: false
    t.text "notes"
    t.string "phone"
    t.string "qualification_status"
    t.string "research_status"
    t.string "sam_cage_code"
    t.string "sam_registration_status"
    t.string "ultimate_parent_name"
    t.datetime "updated_at", null: false
    t.date "verified_at"
    t.string "website"
    t.index ["canonical_name"], name: "index_companies_on_canonical_name"
    t.index ["is_airline"], name: "index_companies_on_is_airline"
    t.index ["normalized_name"], name: "index_companies_on_normalized_name", unique: true
    t.index ["qualification_status"], name: "index_companies_on_qualification_status"
  end

  create_table "connected_accounts", force: :cascade do |t|
    t.string "access_token"
    t.string "access_token_secret"
    t.jsonb "auth"
    t.datetime "created_at", precision: nil, null: false
    t.datetime "expires_at", precision: nil
    t.bigint "owner_id"
    t.string "owner_type"
    t.string "provider"
    t.string "refresh_token"
    t.string "uid"
    t.datetime "updated_at", precision: nil, null: false
    t.index ["owner_id", "owner_type"], name: "index_connected_accounts_on_owner_id_and_owner_type"
  end

  create_table "contacts", force: :cascade do |t|
    t.bigint "company_id", null: false
    t.datetime "created_at", null: false
    t.string "email"
    t.string "first_name"
    t.string "full_name", null: false
    t.string "last_name"
    t.string "linkedin_url"
    t.text "notes"
    t.string "phone"
    t.string "source"
    t.string "title"
    t.datetime "updated_at", null: false
    t.index ["company_id", "email"], name: "index_contacts_on_company_id_and_email", unique: true, where: "((email IS NOT NULL) AND ((email)::text <> ''::text))"
    t.index ["company_id"], name: "index_contacts_on_company_id"
    t.index ["email"], name: "index_contacts_on_email"
  end

  create_table "discovery_runs", force: :cascade do |t|
    t.bigint "airport_id", null: false
    t.integer "companies_created", default: 0, null: false
    t.integer "companies_found", default: 0, null: false
    t.datetime "completed_at"
    t.datetime "created_at", null: false
    t.string "discovery_method"
    t.text "error_details"
    t.integer "possible_duplicates_found", default: 0, null: false
    t.integer "relationships_created", default: 0, null: false
    t.integer "sources_checked", default: 0, null: false
    t.integer "sources_found", default: 0, null: false
    t.datetime "started_at"
    t.string "status", default: "not_started", null: false
    t.text "summary"
    t.datetime "updated_at", null: false
    t.index ["airport_id"], name: "index_discovery_runs_on_airport_id"
    t.index ["started_at"], name: "index_discovery_runs_on_started_at"
    t.index ["status"], name: "index_discovery_runs_on_status"
  end

  create_table "hke_addresses", force: :cascade do |t|
    t.bigint "addressable_id", null: false
    t.string "addressable_type", null: false
    t.string "city"
    t.string "country"
    t.datetime "created_at", null: false
    t.string "description"
    t.string "name"
    t.string "region"
    t.string "street"
    t.datetime "updated_at", null: false
    t.string "zipcode"
    t.index ["addressable_type", "addressable_id"], name: "index_hke_addresses_on_addressable"
  end

  create_table "hke_cemeteries", force: :cascade do |t|
    t.bigint "community_id", null: false
    t.datetime "created_at", null: false
    t.string "description"
    t.string "name"
    t.datetime "updated_at", null: false
    t.index ["community_id"], name: "index_hke_cemeteries_on_community_id"
  end

  create_table "hke_communities", force: :cascade do |t|
    t.bigint "account_id", null: false
    t.string "community_type", null: false
    t.datetime "created_at", null: false
    t.string "description"
    t.string "email_address"
    t.string "name", null: false
    t.string "phone_number"
    t.datetime "updated_at", null: false
    t.index ["account_id"], name: "index_hke_communities_on_account_id"
  end

  create_table "hke_contact_people", force: :cascade do |t|
    t.bigint "community_id", null: false
    t.datetime "created_at", null: false
    t.string "email"
    t.string "first_name"
    t.string "gender"
    t.string "last_name"
    t.string "phone"
    t.datetime "updated_at", null: false
    t.index ["community_id"], name: "index_hke_contact_people_on_community_id"
  end

  create_table "hke_csv_import_logs", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.bigint "csv_import_id", null: false
    t.jsonb "details"
    t.string "level", null: false
    t.text "message", null: false
    t.integer "row_number"
    t.datetime "updated_at", null: false
    t.index ["csv_import_id"], name: "index_hke_csv_import_logs_on_csv_import_id"
  end

  create_table "hke_csv_imports", force: :cascade do |t|
    t.bigint "community_id", null: false
    t.datetime "created_at", null: false
    t.text "errors_data"
    t.integer "existing_deceased", default: 0
    t.integer "failed_rows", default: 0
    t.integer "import_type", default: 0
    t.string "name"
    t.integer "new_deceased", default: 0
    t.integer "processed_rows", default: 0
    t.integer "status", default: 0
    t.integer "successful_rows", default: 0
    t.integer "total_contacts_in_input", default: 0
    t.integer "total_deceased_in_input", default: 0
    t.integer "total_rows", default: 0
    t.datetime "updated_at", null: false
    t.bigint "user_id", null: false
    t.index ["community_id"], name: "index_hke_csv_imports_on_community_id"
    t.index ["user_id"], name: "index_hke_csv_imports_on_user_id"
  end

  create_table "hke_deceased_people", force: :cascade do |t|
    t.bigint "cemetery_id"
    t.string "cemetery_parcel"
    t.string "cemetery_region"
    t.bigint "community_id", null: false
    t.datetime "created_at", null: false
    t.datetime "date_of_death"
    t.string "father_first_name"
    t.string "first_name"
    t.string "gender"
    t.string "hebrew_day_of_death"
    t.string "hebrew_month_of_death"
    t.string "hebrew_year_of_death"
    t.string "last_name"
    t.string "location_of_death"
    t.string "mother_first_name"
    t.string "occupation"
    t.string "organization"
    t.string "religion"
    t.time "time_of_death"
    t.datetime "updated_at", null: false
    t.index ["cemetery_id"], name: "index_hke_deceased_people_on_cemetery_id"
    t.index ["community_id"], name: "index_hke_deceased_people_on_community_id"
  end

  create_table "hke_future_messages", force: :cascade do |t|
    t.integer "approval_status", default: 0
    t.datetime "approved_at"
    t.bigint "approved_by_id"
    t.bigint "community_id", null: false
    t.string "contact_first_name"
    t.string "contact_last_name"
    t.datetime "created_at", null: false
    t.date "date_of_death"
    t.string "deceased_first_name"
    t.string "deceased_last_name"
    t.integer "delivery_method"
    t.string "email"
    t.text "full_message"
    t.string "hebrew_day_of_death"
    t.string "hebrew_month_of_death"
    t.string "hebrew_year_of_death"
    t.integer "message_type"
    t.bigint "messageable_id", null: false
    t.string "messageable_type", null: false
    t.json "metadata"
    t.string "phone"
    t.string "relation_of_deceased_to_contact"
    t.datetime "send_date"
    t.string "token"
    t.datetime "updated_at", null: false
    t.index ["approval_status"], name: "index_hke_future_messages_on_approval_status"
    t.index ["approved_by_id"], name: "index_hke_future_messages_on_approved_by_id"
    t.index ["community_id"], name: "index_hke_future_messages_on_community_id"
    t.index ["messageable_type", "messageable_id"], name: "index_hke_future_messages_on_messageable"
    t.index ["token"], name: "index_hke_future_messages_on_token", unique: true
  end

  create_table "hke_landing_pages", force: :cascade do |t|
    t.text "body"
    t.bigint "community_id", null: false
    t.datetime "created_at", null: false
    t.string "name"
    t.datetime "updated_at", null: false
    t.bigint "user_id", null: false
    t.index ["community_id"], name: "index_hke_landing_pages_on_community_id"
    t.index ["user_id"], name: "index_hke_landing_pages_on_user_id"
  end

  create_table "hke_logs", force: :cascade do |t|
    t.bigint "community_id"
    t.datetime "created_at", null: false
    t.jsonb "details", default: {}
    t.bigint "entity_id"
    t.string "entity_type"
    t.text "error_message"
    t.text "error_trace"
    t.string "error_type"
    t.datetime "event_time", null: false
    t.string "event_type", null: false
    t.inet "ip_address"
    t.string "message_token"
    t.datetime "updated_at", null: false
    t.bigint "user_id"
    t.index ["community_id"], name: "index_hke_logs_on_community_id"
    t.index ["entity_type", "entity_id"], name: "index_hke_logs_on_entity_type_and_entity_id"
    t.index ["message_token"], name: "index_hke_logs_on_message_token"
    t.index ["user_id"], name: "index_hke_logs_on_user_id"
  end

  create_table "hke_preferences", force: :cascade do |t|
    t.boolean "attempt_to_resend_if_no_sent_on_time"
    t.datetime "created_at", null: false
    t.time "daily_sweep_job_time"
    t.string "delivery_priority", array: true
    t.boolean "enable_fallback_delivery_method"
    t.integer "how_many_days_before_yahrzeit_to_send_message", default: [7], array: true
    t.bigint "preferring_id", null: false
    t.string "preferring_type", null: false
    t.string "time_zone"
    t.datetime "updated_at", null: false
    t.index ["preferring_type", "preferring_id"], name: "index_hke_preferences_on_preferring"
  end

  create_table "hke_relations", force: :cascade do |t|
    t.bigint "community_id", null: false
    t.bigint "contact_person_id", null: false
    t.datetime "created_at", null: false
    t.bigint "deceased_person_id", null: false
    t.string "relation_of_deceased_to_contact"
    t.string "token"
    t.datetime "updated_at", null: false
    t.index ["community_id"], name: "index_hke_relations_on_community_id"
    t.index ["contact_person_id"], name: "index_hke_relations_on_contact_person_id"
    t.index ["deceased_person_id"], name: "index_hke_relations_on_deceased_person_id"
  end

  create_table "hke_relations_selections", force: :cascade do |t|
    t.bigint "community_id", null: false
    t.datetime "created_at", null: false
    t.bigint "relation_id", null: false
    t.bigint "selection_id", null: false
    t.datetime "updated_at", null: false
    t.index ["community_id"], name: "index_hke_relations_selections_on_community_id"
    t.index ["relation_id"], name: "index_hke_relations_selections_on_relation_id"
    t.index ["selection_id"], name: "index_hke_relations_selections_on_selection_id"
  end

  create_table "hke_selections", force: :cascade do |t|
    t.bigint "community_id", null: false
    t.datetime "created_at", null: false
    t.string "description"
    t.string "name"
    t.datetime "updated_at", null: false
    t.index ["community_id"], name: "index_hke_selections_on_community_id"
  end

  create_table "hke_sent_messages", force: :cascade do |t|
    t.bigint "community_id", null: false
    t.string "contact_first_name"
    t.string "contact_last_name"
    t.datetime "created_at", null: false
    t.date "date_of_death"
    t.string "deceased_first_name"
    t.string "deceased_last_name"
    t.integer "delivery_method"
    t.string "email"
    t.text "full_message"
    t.string "hebrew_day_of_death"
    t.string "hebrew_month_of_death"
    t.string "hebrew_year_of_death"
    t.integer "message_type"
    t.bigint "messageable_id", null: false
    t.string "messageable_type", null: false
    t.json "metadata"
    t.string "phone"
    t.string "relation_of_deceased_to_contact"
    t.datetime "send_date"
    t.string "token"
    t.string "twilio_message_sid"
    t.datetime "updated_at", null: false
    t.index ["community_id"], name: "index_hke_sent_messages_on_community_id"
    t.index ["messageable_type", "messageable_id"], name: "index_hke_sent_messages_on_messageable"
    t.index ["token"], name: "index_hke_sent_messages_on_token", unique: true
    t.index ["twilio_message_sid"], name: "index_hke_sent_messages_on_twilio_message_sid", unique: true
  end

  create_table "hke_systems", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.string "product_name", default: "Hakhel"
    t.datetime "updated_at", null: false
    t.string "version", default: "1.0"
  end

  create_table "inbound_webhooks", force: :cascade do |t|
    t.text "body"
    t.datetime "created_at", null: false
    t.integer "status", default: 0, null: false
    t.datetime "updated_at", null: false
  end

  create_table "noticed_events", force: :cascade do |t|
    t.bigint "account_id"
    t.datetime "created_at", null: false
    t.integer "notifications_count"
    t.jsonb "params"
    t.bigint "record_id"
    t.string "record_type"
    t.string "type"
    t.datetime "updated_at", null: false
    t.index ["account_id"], name: "index_noticed_events_on_account_id"
    t.index ["record_type", "record_id"], name: "index_noticed_events_on_record"
  end

  create_table "noticed_notifications", force: :cascade do |t|
    t.bigint "account_id"
    t.datetime "created_at", null: false
    t.bigint "event_id", null: false
    t.datetime "read_at", precision: nil
    t.bigint "recipient_id", null: false
    t.string "recipient_type", null: false
    t.datetime "seen_at", precision: nil
    t.string "type"
    t.datetime "updated_at", null: false
    t.index ["account_id"], name: "index_noticed_notifications_on_account_id"
    t.index ["event_id"], name: "index_noticed_notifications_on_event_id"
    t.index ["recipient_type", "recipient_id"], name: "index_noticed_notifications_on_recipient"
  end

  create_table "notification_tokens", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.string "platform", null: false
    t.string "token", null: false
    t.datetime "updated_at", null: false
    t.bigint "user_id"
    t.index ["user_id"], name: "index_notification_tokens_on_user_id"
  end

  create_table "notifications", force: :cascade do |t|
    t.bigint "account_id", null: false
    t.datetime "created_at", null: false
    t.datetime "interacted_at", precision: nil
    t.jsonb "params"
    t.datetime "read_at", precision: nil
    t.bigint "recipient_id", null: false
    t.string "recipient_type", null: false
    t.string "type"
    t.datetime "updated_at", null: false
    t.index ["account_id"], name: "index_notifications_on_account_id"
    t.index ["recipient_type", "recipient_id"], name: "index_notifications_on_recipient_type_and_recipient_id"
  end

  create_table "pay_charges", force: :cascade do |t|
    t.integer "amount", null: false
    t.integer "amount_refunded"
    t.integer "application_fee_amount"
    t.datetime "created_at", precision: nil, null: false
    t.string "currency"
    t.bigint "customer_id"
    t.jsonb "data"
    t.jsonb "metadata"
    t.jsonb "object"
    t.string "processor_id", null: false
    t.string "stripe_account"
    t.integer "subscription_id"
    t.string "type"
    t.datetime "updated_at", precision: nil, null: false
    t.index ["customer_id", "processor_id"], name: "index_pay_charges_on_customer_id_and_processor_id", unique: true
  end

  create_table "pay_customers", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.jsonb "data"
    t.boolean "default"
    t.datetime "deleted_at", precision: nil
    t.jsonb "object"
    t.bigint "owner_id"
    t.string "owner_type"
    t.string "processor"
    t.string "processor_id"
    t.string "stripe_account"
    t.string "type"
    t.datetime "updated_at", null: false
    t.index ["owner_type", "owner_id", "deleted_at"], name: "customer_owner_processor_index"
    t.index ["processor", "processor_id"], name: "index_pay_customers_on_processor_and_processor_id"
  end

  create_table "pay_merchants", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.jsonb "data"
    t.boolean "default"
    t.bigint "owner_id"
    t.string "owner_type"
    t.string "processor"
    t.string "processor_id"
    t.string "type"
    t.datetime "updated_at", null: false
    t.index ["owner_type", "owner_id", "processor"], name: "index_pay_merchants_on_owner_type_and_owner_id_and_processor"
  end

  create_table "pay_payment_methods", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.bigint "customer_id"
    t.jsonb "data"
    t.boolean "default"
    t.string "payment_method_type"
    t.string "processor_id"
    t.string "stripe_account"
    t.string "type"
    t.datetime "updated_at", null: false
    t.index ["customer_id", "processor_id"], name: "index_pay_payment_methods_on_customer_id_and_processor_id", unique: true
  end

  create_table "pay_subscriptions", id: :serial, force: :cascade do |t|
    t.decimal "application_fee_percent", precision: 8, scale: 2
    t.datetime "created_at", precision: nil
    t.datetime "current_period_end"
    t.datetime "current_period_start"
    t.bigint "customer_id"
    t.jsonb "data"
    t.datetime "ends_at", precision: nil
    t.jsonb "metadata"
    t.boolean "metered"
    t.string "name", null: false
    t.jsonb "object"
    t.string "pause_behavior"
    t.datetime "pause_resumes_at"
    t.datetime "pause_starts_at"
    t.string "payment_method_id"
    t.string "processor_id", null: false
    t.string "processor_plan", null: false
    t.integer "quantity", default: 1, null: false
    t.string "status"
    t.string "stripe_account"
    t.datetime "trial_ends_at", precision: nil
    t.string "type"
    t.datetime "updated_at", precision: nil
    t.index ["customer_id", "processor_id"], name: "index_pay_subscriptions_on_customer_id_and_processor_id", unique: true
    t.index ["metered"], name: "index_pay_subscriptions_on_metered"
    t.index ["pause_starts_at"], name: "index_pay_subscriptions_on_pause_starts_at"
  end

  create_table "pay_webhooks", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.jsonb "event"
    t.string "event_type"
    t.string "processor"
    t.datetime "updated_at", null: false
  end

  create_table "plans", force: :cascade do |t|
    t.integer "amount", default: 0, null: false
    t.string "braintree_id"
    t.boolean "charge_per_unit"
    t.string "contact_url"
    t.datetime "created_at", precision: nil, null: false
    t.string "currency"
    t.string "description"
    t.jsonb "details"
    t.string "fake_processor_id"
    t.boolean "hidden"
    t.string "interval", null: false
    t.integer "interval_count", default: 1
    t.string "lemon_squeezy_id"
    t.string "name", null: false
    t.string "paddle_billing_id"
    t.string "paddle_classic_id"
    t.string "stripe_id"
    t.integer "trial_period_days", default: 0
    t.string "unit_label"
    t.datetime "updated_at", precision: nil, null: false
  end

  create_table "sources", force: :cascade do |t|
    t.datetime "accessed_at"
    t.bigint "airport_id"
    t.string "content_type"
    t.datetime "created_at", null: false
    t.text "notes"
    t.string "original_filename"
    t.string "processing_status", default: "pending", null: false
    t.date "publication_date"
    t.string "referring_url"
    t.string "sha256"
    t.string "source_type", null: false
    t.string "title"
    t.datetime "updated_at", null: false
    t.string "url"
    t.index ["airport_id"], name: "index_sources_on_airport_id"
    t.index ["processing_status"], name: "index_sources_on_processing_status"
    t.index ["source_type"], name: "index_sources_on_source_type"
  end

  create_table "users", force: :cascade do |t|
    t.datetime "accepted_privacy_at", precision: nil
    t.datetime "accepted_terms_at", precision: nil
    t.boolean "admin"
    t.datetime "announcements_read_at", precision: nil
    t.bigint "community_id"
    t.datetime "confirmation_sent_at", precision: nil
    t.string "confirmation_token"
    t.datetime "confirmed_at", precision: nil
    t.datetime "created_at", precision: nil, null: false
    t.string "email", default: "", null: false
    t.string "encrypted_password", default: "", null: false
    t.string "first_name"
    t.datetime "invitation_accepted_at", precision: nil
    t.datetime "invitation_created_at", precision: nil
    t.integer "invitation_limit"
    t.datetime "invitation_sent_at", precision: nil
    t.string "invitation_token"
    t.integer "invitations_count", default: 0
    t.bigint "invited_by_id"
    t.string "invited_by_type"
    t.string "last_name"
    t.integer "last_otp_timestep"
    t.virtual "name", type: :string, as: "(((first_name)::text || ' '::text) || (COALESCE(last_name, ''::character varying))::text)", stored: true
    t.text "otp_backup_codes"
    t.boolean "otp_required_for_login"
    t.string "otp_secret"
    t.jsonb "preferences"
    t.string "preferred_language"
    t.datetime "remember_created_at", precision: nil
    t.datetime "reset_password_sent_at", precision: nil
    t.string "reset_password_token"
    t.jsonb "roles", default: {}, null: false
    t.string "time_zone"
    t.string "unconfirmed_email"
    t.datetime "updated_at", precision: nil, null: false
    t.index ["community_id"], name: "index_users_on_community_id"
    t.index ["email"], name: "index_users_on_email", unique: true
    t.index ["invitation_token"], name: "index_users_on_invitation_token", unique: true
    t.index ["invitations_count"], name: "index_users_on_invitations_count"
    t.index ["invited_by_id"], name: "index_users_on_invited_by_id"
    t.index ["invited_by_type", "invited_by_id"], name: "index_users_on_invited_by_type_and_invited_by_id"
    t.index ["reset_password_token"], name: "index_users_on_reset_password_token", unique: true
    t.index ["roles"], name: "index_users_on_roles", using: :gin
  end

  add_foreign_key "account_invitations", "accounts"
  add_foreign_key "account_invitations", "users", column: "invited_by_id"
  add_foreign_key "account_users", "accounts"
  add_foreign_key "account_users", "users"
  add_foreign_key "accounts", "users", column: "owner_id"
  add_foreign_key "active_storage_variant_records", "active_storage_blobs", column: "blob_id"
  add_foreign_key "activity_logs", "airports"
  add_foreign_key "activity_logs", "discovery_runs"
  add_foreign_key "airport_company_relationships", "airports"
  add_foreign_key "airport_company_relationships", "companies"
  add_foreign_key "api_tokens", "users"
  add_foreign_key "contacts", "companies"
  add_foreign_key "discovery_runs", "airports"
  add_foreign_key "hke_cemeteries", "hke_communities", column: "community_id"
  add_foreign_key "hke_communities", "accounts"
  add_foreign_key "hke_contact_people", "hke_communities", column: "community_id"
  add_foreign_key "hke_csv_import_logs", "hke_csv_imports", column: "csv_import_id"
  add_foreign_key "hke_csv_imports", "hke_communities", column: "community_id"
  add_foreign_key "hke_csv_imports", "users"
  add_foreign_key "hke_deceased_people", "hke_cemeteries", column: "cemetery_id"
  add_foreign_key "hke_deceased_people", "hke_communities", column: "community_id"
  add_foreign_key "hke_future_messages", "hke_communities", column: "community_id"
  add_foreign_key "hke_future_messages", "users", column: "approved_by_id"
  add_foreign_key "hke_landing_pages", "hke_communities", column: "community_id"
  add_foreign_key "hke_landing_pages", "users"
  add_foreign_key "hke_relations", "hke_communities", column: "community_id"
  add_foreign_key "hke_relations", "hke_contact_people", column: "contact_person_id"
  add_foreign_key "hke_relations", "hke_deceased_people", column: "deceased_person_id"
  add_foreign_key "hke_relations_selections", "hke_communities", column: "community_id"
  add_foreign_key "hke_relations_selections", "hke_relations", column: "relation_id"
  add_foreign_key "hke_relations_selections", "hke_selections", column: "selection_id"
  add_foreign_key "hke_selections", "hke_communities", column: "community_id"
  add_foreign_key "hke_sent_messages", "hke_communities", column: "community_id"
  add_foreign_key "pay_charges", "pay_customers", column: "customer_id"
  add_foreign_key "pay_payment_methods", "pay_customers", column: "customer_id"
  add_foreign_key "pay_subscriptions", "pay_customers", column: "customer_id"
  add_foreign_key "sources", "airports"
  add_foreign_key "users", "hke_communities", column: "community_id"
end
