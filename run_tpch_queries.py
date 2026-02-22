#!/usr/bin/env python3
import duckdb
import yaml
import pandas as pd
from pathlib import Path
import os
import time
import argparse

def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)

def open_ducklake(cfg):
    db_path = cfg["metadata"]["duckdb_file"]
    data_path = f"s3://{cfg['storage']['bucket']}/{cfg['storage']['prefix']}"
    alias = cfg["catalog"]["alias"]

    con = duckdb.connect(database=":memory:")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("INSTALL aws; LOAD aws;")
    con.execute("INSTALL ducklake; LOAD ducklake;")
    con.execute(f"""
        CREATE OR REPLACE SECRET minio (
          TYPE S3,
          KEY_ID '{cfg['storage'].get('access_key', 'minioadmin')}',
          SECRET '{cfg['storage'].get('secret_key', 'minioadmin')}',
          ENDPOINT '{cfg['storage']['endpoint'].replace('http://','').replace('https://','')}',
          URL_STYLE '{cfg['storage'].get('url_style','path')}',
          USE_SSL {'true' if cfg['storage'].get('use_ssl', False) else 'false'},
          REGION '{cfg['storage'].get('region','us-east-1')}'
        );
    """)
    con.execute(f"ATTACH 'ducklake:{db_path}' AS {alias} (DATA_PATH '{data_path}');")
    con.execute(f"USE {alias};")
    return con

def open_reference(scale=1):
    local_db = f"tpch-sf{scale}.duckdb"
    if not os.path.exists(local_db):
        raise FileNotFoundError(
            f"{local_db} not found — run bootstrap/load first to generate it."
        )
    con = duckdb.connect(database=":memory:")
    con.execute("INSTALL tpch; LOAD tpch;")
    con.execute(f"ATTACH '{local_db}' AS tpch_ref;")
    return con


def open_local_db(local_db: str = None, scale: int = 1):
    """
    Open a local DuckDB database for benchmarking.
    
    Args:
        local_db: Path to the local DuckDB file (default: tpch-sf{scale}.duckdb)
        scale: TPC-H scale factor (used if local_db is not specified)
    
    Returns:
        DuckDB connection with tpch extension loaded
    """
    if local_db is None:
        local_db = f"tpch-sf{scale}.duckdb"
    
    if not os.path.exists(local_db):
        raise FileNotFoundError(
            f"{local_db} not found — run bootstrap/load first to generate it."
        )
    
    con = duckdb.connect(database=":memory:")
    con.execute("INSTALL tpch; LOAD tpch;")
    con.execute(f"ATTACH '{local_db}' AS tpch_local;")
    con.execute("USE tpch_local;")
    return con

def run_query(con, sql, alias=None):
    if alias:
        sql = sql.replace("FROM ", f"FROM {alias}.")
    return con.execute(sql).fetch_df()

def validate_tpch(cfg, scale=1, query_ids=None, save_queries=True, output_dir="tpch_validation"):
    """
    Run TPC-H queries and validate results between DuckLake and reference database.
    
    Args:
        cfg: Configuration dictionary
        scale: TPC-H scale factor
        query_ids: List of query IDs to run (default: 1-22)
        save_queries: Whether to save all queries to a SQL file
        output_dir: Directory for output files
    """
    if not query_ids:
        query_ids = range(1, 23)

    ducklake_con = open_ducklake(cfg)
    ref_con = open_reference(scale)

    results_dir = Path(output_dir)
    results_dir.mkdir(exist_ok=True)

    summary = []
    all_queries = []  # For saving to SQL file
    timing_results = []  # For timing information
    total_start_time = time.time()

    for q in query_ids:
        sql = ducklake_con.execute(
            f"SELECT query FROM tpch_queries() WHERE query_nr={q};"
        ).fetchone()[0]
        
        # Save query for SQL file
        all_queries.append(f"-- Query {q}\n{sql};\n")
        
        print(f"\n[Q{q:02d}] Validating...")

        try:
            # Measure reference query time
            ref_con.execute("USE tpch_ref;")
            ref_start = time.time()
            df_ref = ref_con.execute(sql).fetch_df()
            ref_time_ms = (time.time() - ref_start) * 1000
            
            # Measure DuckLake query time
            ducklake_con.execute(f"USE {cfg['catalog']['alias']};")
            dl_start = time.time()
            df_dl = ducklake_con.execute(sql).fetch_df()
            dl_time_ms = (time.time() - dl_start) * 1000

            match, reason = True, ""

            if list(df_ref.columns) != list(df_dl.columns):
                match, reason = False, "Column mismatch"
            elif len(df_ref) != len(df_dl):
                match, reason = False, f"Row count mismatch ({len(df_ref)} vs {len(df_dl)})"
            else:
                try:
                    pd.testing.assert_frame_equal(
                        df_ref.sort_index(axis=1),
                        df_dl.sort_index(axis=1),
                        atol=1e-6,
                        check_dtype=False,
                        check_like=True,
                    )
                except AssertionError:
                    match, reason = False, "Data mismatch"

            summary.append({"query": f"Q{q:02d}", "match": match, "reason": reason})
            timing_results.append({
                "query": f"Q{q:02d}",
                "ref_time_ms": round(ref_time_ms, 2),
                "ducklake_time_ms": round(dl_time_ms, 2),
                "match": match
            })
            print(f"[{'✓' if match else '✗'}] {reason or 'Results match'}")
            print(f"    Reference: {ref_time_ms:.2f}ms | DuckLake: {dl_time_ms:.2f}ms")

            if not match:
                df_ref.to_csv(results_dir / f"q{q:02d}_ref.csv", index=False)
                df_dl.to_csv(results_dir / f"q{q:02d}_ducklake.csv", index=False)

        except Exception as e:
            summary.append({"query": f"Q{q:02d}", "match": False, "reason": str(e)})
            timing_results.append({
                "query": f"Q{q:02d}",
                "ref_time_ms": None,
                "ducklake_time_ms": None,
                "match": False,
                "error": str(e)
            })
            print(f"[x] Error executing Q{q}: {e}")

    total_time_ms = (time.time() - total_start_time) * 1000

    # Save validation summary
    pd.DataFrame(summary).to_csv(results_dir / "validation_summary.csv", index=False)
    print(f"\nValidation summary saved to {results_dir}/validation_summary.csv")
    
    # Save timing results
    timing_df = pd.DataFrame(timing_results)
    timing_df.to_csv(results_dir / "query_timing.csv", index=False)
    print(f"Query timing saved to {results_dir}/query_timing.csv")
    
    # Print timing summary
    print("\n" + "=" * 60)
    print("TIMING SUMMARY")
    print("=" * 60)
    print(f"{'Query':<8} {'Ref (ms)':<12} {'DuckLake (ms)':<15} {'Match'}")
    print("-" * 60)
    for t in timing_results:
        ref_t = f"{t['ref_time_ms']:.2f}" if t['ref_time_ms'] else "N/A"
        dl_t = f"{t['ducklake_time_ms']:.2f}" if t['ducklake_time_ms'] else "N/A"
        match_str = "✓" if t['match'] else "✗"
        print(f"{t['query']:<8} {ref_t:<12} {dl_t:<15} {match_str}")
    print("-" * 60)
    print(f"Total execution time: {total_time_ms:.2f} ms ({total_time_ms/1000:.2f} seconds)")
    print("=" * 60)
    
    # Save all queries to SQL file
    if save_queries:
        sql_file_path = results_dir / "tpch_all_queries.sql"
        with open(sql_file_path, "w") as f:
            f.write("-- TPC-H Queries (Scale Factor: {})\n".format(scale))
            f.write("-- Generated by run_tpch_queries.py\n\n")
            f.write("\n".join(all_queries))
        print(f"All queries saved to {sql_file_path}")


def run_benchmark(cfg, scale=1, query_ids=None, iterations=1, output_dir="tpch_benchmark",
                  target="ducklake", local_db=None):
    """
    Run TPC-H queries and collect timing statistics.
    
    Args:
        cfg: Configuration dictionary
        scale: TPC-H scale factor
        query_ids: List of query IDs to run (default: 1-22)
        iterations: Number of times to run each query (default: 1)
        output_dir: Directory for output files
        target: Target database - "ducklake" for DuckLake or "duckdb" for local DuckDB
        local_db: Path to local DuckDB file (only for target="duckdb")
    """
    if not query_ids:
        query_ids = range(1, 23)

    # Open connection based on target
    if target == "duckdb":
        con = open_local_db(local_db=local_db, scale=scale)
        target_name = "DuckDB (local)"
        use_schema = "tpch_local"
    else:  # ducklake
        con = open_ducklake(cfg)
        target_name = "DuckLake"
        use_schema = cfg['catalog']['alias']

    results_dir = Path(output_dir)
    results_dir.mkdir(exist_ok=True)

    all_queries = []
    # Detailed timing: each attempt for each query
    detailed_timing = []
    # Summary timing: aggregated per query
    timing_summary = []
    total_start_time = time.time()

    print(f"Running TPC-H benchmark (scale={scale}, iterations={iterations}) on {target_name}...")
    print("=" * 70)

    for q in query_ids:
        sql = con.execute(
            f"SELECT query FROM tpch_queries() WHERE query_nr={q};"
        ).fetchone()[0]
        
        all_queries.append(f"-- Query {q}\n{sql};\n")
        
        query_times = []
        query_rows = 0
        query_status = "success"
        query_error = None
        
        print(f"[Q{q:02d}] Running {iterations} iteration(s)...")

        for attempt in range(1, iterations + 1):
            try:
                con.execute(f"USE {use_schema};")
                start = time.time()
                df = con.execute(sql).fetch_df()
                elapsed_ms = (time.time() - start) * 1000
                
                query_times.append(elapsed_ms)
                query_rows = len(df)
                
                detailed_timing.append({
                    "query": f"Q{q:02d}",
                    "attempt": attempt,
                    "time_ms": round(elapsed_ms, 2),
                    "rows": query_rows,
                    "status": "success"
                })
                print(f"    Attempt {attempt}/{iterations}: {elapsed_ms:.2f} ms")

            except Exception as e:
                query_status = f"error: {str(e)}"
                query_error = str(e)
                detailed_timing.append({
                    "query": f"Q{q:02d}",
                    "attempt": attempt,
                    "time_ms": None,
                    "rows": 0,
                    "status": f"error: {str(e)}"
                })
                print(f"    Attempt {attempt}/{iterations}: ERROR - {e}")
        
        # Calculate statistics for this query
        if query_times:
            avg_time = sum(query_times) / len(query_times)
            min_time = min(query_times)
            max_time = max(query_times)
            timing_summary.append({
                "query": f"Q{q:02d}",
                "iterations": iterations,
                "avg_time_ms": round(avg_time, 2),
                "min_time_ms": round(min_time, 2),
                "max_time_ms": round(max_time, 2),
                "total_time_ms": round(sum(query_times), 2),
                "rows": query_rows,
                "status": query_status
            })
        else:
            timing_summary.append({
                "query": f"Q{q:02d}",
                "iterations": iterations,
                "avg_time_ms": None,
                "min_time_ms": None,
                "max_time_ms": None,
                "total_time_ms": None,
                "rows": 0,
                "status": query_status,
                "error": query_error
            })

    total_time_ms = (time.time() - total_start_time) * 1000

    # Save detailed timing results (each attempt)
    detailed_df = pd.DataFrame(detailed_timing)
    detailed_df.to_csv(results_dir / "benchmark_detailed_timing.csv", index=False)
    
    # Save summary timing results (aggregated per query)
    summary_df = pd.DataFrame(timing_summary)
    summary_df.to_csv(results_dir / "benchmark_summary.csv", index=False)
    
    # Save all queries
    sql_file_path = results_dir / "tpch_all_queries.sql"
    with open(sql_file_path, "w") as f:
        f.write("-- TPC-H Queries (Scale Factor: {})\n".format(scale))
        f.write("-- Target: {}\n".format(target_name))
        f.write("-- Generated by run_tpch_queries.py\n\n")
        f.write("\n".join(all_queries))
    
    # Print summary
    print("\n" + "=" * 70)
    print(f"BENCHMARK SUMMARY ({target_name})")
    print("=" * 70)
    if iterations > 1:
        print(f"{'Query':<8} {'Avg (ms)':<12} {'Min (ms)':<12} {'Max (ms)':<12} {'Rows':<10} {'Status'}")
        print("-" * 70)
        for t in timing_summary:
            avg_str = f"{t['avg_time_ms']:.2f}" if t['avg_time_ms'] else "N/A"
            min_str = f"{t['min_time_ms']:.2f}" if t['min_time_ms'] else "N/A"
            max_str = f"{t['max_time_ms']:.2f}" if t['max_time_ms'] else "N/A"
            print(f"{t['query']:<8} {avg_str:<12} {min_str:<12} {max_str:<12} {t['rows']:<10} {t['status']}")
    else:
        print(f"{'Query':<8} {'Time (ms)':<12} {'Rows':<10} {'Status'}")
        print("-" * 70)
        for t in timing_summary:
            time_str = f"{t['avg_time_ms']:.2f}" if t['avg_time_ms'] else "N/A"
            print(f"{t['query']:<8} {time_str:<12} {t['rows']:<10} {t['status']}")
    print("-" * 70)
    print(f"Total benchmark time: {total_time_ms:.2f} ms ({total_time_ms/1000:.2f} seconds)")
    print("=" * 70)
    print(f"\nResults saved to {results_dir}/")
    print(f"  - benchmark_detailed_timing.csv (each attempt)")
    print(f"  - benchmark_summary.csv (aggregated per query)")
    print(f"  - tpch_all_queries.sql (all queries)")


def main():
    parser = argparse.ArgumentParser(description="TPC-H query runner for DuckLake")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--scale", type=int, help="TPC-H scale factor (overrides config)")
    parser.add_argument("--queries", type=str, help="Comma-separated query IDs to run (e.g., '1,3,5')")
    parser.add_argument("--output", default="tpch_benchmark", help="Output directory")
    parser.add_argument("--benchmark", action="store_true",
                        help="Run benchmark mode (no validation, just timing)")
    parser.add_argument("--target", choices=["ducklake", "duckdb"], default="ducklake",
                        help="Target database: 'ducklake' for DuckLake, 'duckdb' for local DuckDB file (default: ducklake)")
    parser.add_argument("--local-db", type=str,
                        help="Path to local DuckDB file (for --target duckdb, default: tpch-sf{scale}.duckdb)")
    parser.add_argument("--iterations", "-n", type=int, default=1,
                        help="Number of iterations for each query (default: 1)")
    parser.add_argument("--no-save-queries", action="store_true",
                        help="Don't save queries to SQL file")
    
    args = parser.parse_args()
    
    cfg = load_config(args.config)
    scale = args.scale or cfg["tpch"].get("default_scale", 1)
    
    query_ids = None
    if args.queries:
        query_ids = [int(q.strip()) for q in args.queries.split(",")]
    
    if args.benchmark:
        run_benchmark(cfg, scale=scale, query_ids=query_ids,
                      iterations=args.iterations, output_dir=args.output,
                      target=args.target, local_db=args.local_db)
    else:
        validate_tpch(cfg, scale=scale, query_ids=query_ids,
                      save_queries=not args.no_save_queries, output_dir=args.output)


if __name__ == "__main__":
    main()
