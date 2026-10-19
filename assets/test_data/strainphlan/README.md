# StrainPhlAn test data

Six single-end HMP gut metagenome samples from the
[StrainPhlAn 4.1 tutorial](https://github.com/biobakery/MetaPhlAn/wiki/StrainPhlAn-4.1).
Three subjects, two timepoints each:

| sampleID  | subjectID |
|-----------|-----------|
| SRS055982 | 638754422 |
| SRS022137 | 638754422 |
| SRS019161 | 763496533 |
| SRS013951 | 763496533 |
| SRS014613 | 763840445 |
| SRS064276 | 763840445 |

Used by `conf/test_strainphlan.config` via `assets/samplesheet-strainphlan.csv`.

## How these files were made

The tutorial ships them as `.fastq.bz2`; the pipeline schema
(`assets/schema_input.json`) requires `.fastq.gz`. Download and recompress:

```bash
base="http://cmprod1.cibio.unitn.it/biobakery4/github_strainphlan4/fastq"
for s in SRS013951 SRS014613 SRS019161 SRS022137 SRS055982 SRS064276; do
  curl -sL "$base/$s.fastq.bz2" | bunzip2 | gzip > "$s.fastq.gz"
done
```

The `.fastq.gz` files are git-ignored (see `.gitignore`) — regenerate with the
command above rather than committing them.
