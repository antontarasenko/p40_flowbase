{
  python,
  pyproject-nix,
  projectRoot,
}:
let
  project = pyproject-nix.lib.project.loadPyproject {
    inherit projectRoot;
  };

  pythonPkgAttrs = project.renderers.buildPythonPackage {
    inherit python;
  };
in
{
  inherit project;

  inherit pythonPkgAttrs;

  package = python.pkgs.buildPythonPackage pythonPkgAttrs;

  devEnv = python.withPackages (ps:
    (project.renderers.withPackages {
      inherit python;
      extras = [ "dev" ];
    }) ps
    ++ [
      ps.ipython
      ps.pip
    ]
  );
}
