# Airport Service Provider Discovery Platform

Internal tool for identifying companies that provide operational services at U.S. airports.
Built on Jumpstart Pro Rails 8.1.

## Requirements

* Ruby 4.0+
* PostgreSQL 12+
* Redis (for Sidekiq)
* Python 3.12+ (for FAA NASR data parsing)
* Libvips or Imagemagick

## Setup

```bash
bin/setup
```

## Running

```bash
bin/dev
```

Starts Rails server, CSS/JS watching, and Sidekiq via Overmind.

## FAA Airport Import

Airport data is imported from the [FAA NASR subscription dataset](https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/), updated every 28 days.

### Import all U.S. airports

```bash
rake airports:import_faa
```

Downloads the current NASR ZIP, extracts airport records, and upserts all U.S. airports. Safe to re-run — will not create duplicates.

### Import from a local file

```bash
rake airports:import_faa[/path/to/APT_BASE.csv]
rake airports:import_faa[/path/to/nasr.zip]
```

Accepts a local CSV (`APT_BASE.csv` format), ZIP, or fixed-width `APT.txt` file.

The Python parser is at `lib/faa_import/parse_nasr.py` and can be used standalone:

```bash
python3 lib/faa_import/parse_nasr.py /path/to/file.csv
```

Outputs a JSON array of airport records to stdout.

## Data Model (Stage 1)

| Model | Purpose |
|-------|---------|
| `Airport` | One FAA airport or landing facility, keyed by `faa_code` |
| `Source` | A page, file, or document used during discovery |
| `DiscoveryRun` | Per-airport discovery attempt with status and counters |
| `ActivityLog` | Structured log of every meaningful system action |

Discovery statuses: `not_started`, `queued`, `running`, `completed`, `completed_no_sources`, `completed_no_providers`, `needs_review`, `failed`.

## Testing

```bash
bin/rails test
```

273 tests, all passing. Integration tests use a fixture CSV at `test/fixtures/files/sample_apt.csv` — no network access required.

## Health Check

```
GET /health  →  {"status":"ok","timestamp":"..."}
GET /up      →  Rails built-in boot check
```

## Create Your Repository

Create a [new Git](https://github.com/new) repository for your project. Then you can clone Jumpstart Pro and push it to your new repository.

```bash
git clone https://github.com/jumpstart-pro/jumpstart-pro-rails.git myapp
cd myapp
git remote rename origin jumpstart-pro
git remote add origin https://github.com/your-account/your-repo.git # Replace with your new Git repository url
git push -u origin main
```

## Initial Setup

First, edit `config/database.yml` and change the database credentials for your server.

Run `bin/setup` to install Ruby and JavaScript dependencies and setup your database.

```bash
bin/setup
```

## Running Jumpstart Pro Rails

To run your application, you'll use the `bin/dev` command:

```bash
bin/dev
```

This starts up Overmind running the processes defined in `Procfile.dev`. We've configured this to run the Rails server, CSS bundling, and JS bundling out of the box. You can add background workers like Sidekiq, the Stripe CLI, etc to have them run at the same time.

#### Running on Windows

See the [Installation docs](https://jumpstartrails.com/docs/installation#windows)

#### Running with Docker or Docker Compose

See the [Installation docs](https://jumpstartrails.com/docs/installation#docker)

## Merging Updates

To merge changes from Jumpstart Pro, you will merge from the `jumpstart-pro` remote.

```bash
git fetch jumpstart-pro
git merge jumpstart-pro/main
```

## Contributing

If you have an improvement you'd like to share, create a fork of the repository and send us a pull request.
