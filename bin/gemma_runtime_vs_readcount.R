#!/usr/bin/env Rscript
# Fit runtime ~ readcount for profile_taxa and profile_function (linear, then
# quadratic/cubic), on the TSV from gemma_join_readcount_runtime.py. Prints
# model summaries (R^2, coefficients) and saves a scatter+fit plot per process.
#
# Usage:
#   /home/ubuntu/miniconda3/envs/humann4/bin/Rscript bin/gemma_runtime_vs_readcount.R \
#     <input.tsv> <output_dir>

suppressMessages(library(tidyverse))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) stop("usage: gemma_runtime_vs_readcount.R <input.tsv> <output_dir>")
in_path <- args[1]
out_dir <- args[2]
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

df <- read_tsv(in_path, show_col_types = FALSE)

fit_and_plot <- function(df, y_col, label) {
  d <- df %>%
    select(sample, readcount, y = all_of(y_col)) %>%
    drop_na(readcount, y)

  cat(sprintf("\n=== %s (n=%d) ===\n", label, nrow(d)))

  m1 <- lm(y ~ readcount, data = d)
  cat(sprintf("linear:    R^2=%.4f  y = %.3e*readcount + %.3f\n",
              summary(m1)$r.squared, coef(m1)[2], coef(m1)[1]))

  m2 <- lm(y ~ poly(readcount, 2, raw = TRUE), data = d)
  cat(sprintf("quadratic: R^2=%.4f\n", summary(m2)$r.squared))

  m3 <- lm(y ~ poly(readcount, 3, raw = TRUE), data = d)
  cat(sprintf("cubic:     R^2=%.4f\n", summary(m3)$r.squared))

  p <- ggplot(d, aes(x = readcount, y = y)) +
    geom_point(alpha = 0.4, size = 1) +
    geom_smooth(method = "lm", formula = y ~ x, color = "steelblue", se = FALSE) +
    geom_smooth(method = "lm", formula = y ~ poly(x, 3, raw = TRUE), color = "firebrick", se = FALSE) +
    labs(title = sprintf("%s: runtime vs read count", label),
         subtitle = "blue = linear fit, red = cubic fit",
         x = "read count (pairs)", y = "runtime (minutes)") +
    theme_minimal()

  out_file <- file.path(out_dir, sprintf("gemma_%s_vs_readcount.png", y_col))
  ggsave(out_file, p, width = 8, height = 5, dpi = 150)
  cat(sprintf("saved: %s\n", out_file))

  list(linear = m1, quadratic = m2, cubic = m3)
}

fit_and_plot(df, "profile_taxa_min", "profile_taxa")
fit_and_plot(df, "profile_function_min", "profile_function")
