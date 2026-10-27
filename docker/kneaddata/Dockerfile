FROM condaforge/miniforge3:latest

# Match the cohort protocol: KneadData 0.10.0 and Trimmomatic 0.39.
RUN mamba create -y -p /opt/kneaddata --override-channels -c conda-forge -c bioconda \
        python=3.10 kneaddata=0.10.0 trimmomatic=0.39 && \
    mamba clean --all --yes

ENV PATH="/opt/kneaddata/bin:${PATH}"

# This KneadData release searches PATH for a JAR, not the Conda wrapper.
RUN python -c 'import glob, os; jars = glob.glob("/opt/kneaddata/share/trimmomatic-*/trimmomatic*.jar"); assert len(jars) == 1, jars; os.symlink(jars[0], "/opt/kneaddata/bin/trimmomatic-0.39.jar")' && \
    kneaddata --version && \
    bowtie2 --version && \
    trimmomatic -version
