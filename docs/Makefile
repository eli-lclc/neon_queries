SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = source
BUILDDIR      = build

# Help target
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

# Setup gh-pages worktree
setup-gh-pages:
	@if not exist "$(BUILDDIR)/html/.git" (
		echo Setting up gh-pages worktree...
		if not exist "$(BUILDDIR)" mkdir $(BUILDDIR)
		cd $(BUILDDIR) && git worktree add html gh-pages
	)

# Clean target
clean:
	@$(SPHINXBUILD) -M clean "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
	@if exist "$(BUILDDIR)/html/.git" (
		echo "Removing existing gh-pages worktree..."
		cd $(BUILDDIR) && git worktree remove html
	)
	@if not exist "$(BUILDDIR)/html/.git" (
		echo "Re-adding gh-pages worktree..."
		cd $(BUILDDIR) && git worktree add html gh-pages
	)


# Catch-all target
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
	@if not exist "$(BUILDDIR)/html/.git" (
		echo Setting up gh-pages worktree...
		cd $(BUILDDIR) && git worktree add html gh-pages
	)
