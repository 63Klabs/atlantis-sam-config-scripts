# Set Up Account Including CloudFormation Role for Developers

> Note: This step may have already been done for you if you are provided an account from your AWS administrator, supervisor, or instructor. If you are working on your **personal** AWS account, then please proceed in installing and configuring the SAM Config repository for your organization.

## 1. Set Up Configuration Repository

The repository can reside in the repository provider of your choice (CodeCommit, GitHub, GitLab, etc).

Initialize a new repository and give it a name to promote it as the central repository for your organization's (or team or org unit's) SAM Configuration files, such as: `sam-config` (It may be helpful to append an account identifer if you will be maintaining/using several SAM Config repos even if across accounts).

Then, download and extract the Atlantis Platform CloudFormation Configuration Repository For Serverless Deployments into your new repository.

```bash
# Downloads and extracts files for the repository
curl -L -o repo.zip "https://github.com/63klabs/atlantis-cfn-configuration-repo-for-serverless-deployments/archive/refs/heads/main.zip" && unzip -o repo.zip && DIR=$(ls -d */ | head -1) && mv "${DIR}docs" . && mv "${DIR}cli" . && mv "${DIR}defaults" . && mv "${DIR}README.md" . && mv "${DIR}.gitignore" . 2>/dev/null && rm -rf repo.zip && rm -rf "$DIR"
```

> Note: The above command pulls the latest commit from the 63Klabs repository. You can point it to a `zip` in the releases as well. However, in the end you will set up the location to retrieve updates in the settings (release, main, S3), so once you run the `update.py` script you will get the version/release you desire.

This repository will host the cli and deployment configurations for storage, network, pipeline, and IAM roles. Developers will use the cli to manage their pipeline and storage configurations and pull, commit, and push changes to maintain a central source of truth for configurations.

> It is important to **pull** any changes to the local machine, **config** and **deploy** an infrastructure stack using the cli, and then **commit** and **push** the configuration changes back to the remote repository for proper version control.

## 2. Local Machine Set-Up

In order to run the scripts you will need to set-up as instructed in [Set-Up Local Environment](../00-Set-Up-Local-Environment.md).

## 3. Determine Default Settings and Naming Conventions

The Principle of Least Privilege is maintained through resource naming and tagging.

At the very base is the naming `Prefix`. Think of a `Prefix` as a namespace that groups applications together. An account may have a single Prefix, or multiple Prefix namespaces. Each Prefix has its own base configuration, assigned users, and permissions. Segmenting too much could create a maintenance nightmare. Segmenting too little can create a permissions nightmare. 

If you are using AWS Organization accounts and you have developer teams assigned to each, then you would most likely have just one Prefix per AWS Org account. If you have many teams in a single account (not recommended) you could use Prefix namespaces to separate out and enforce permissions.

To start out, you must determine the following:

- Prefix (namespace)
- Role Path (optional but recommended - a suggested `RolePath` is provided in defaults)
- Service Role Path (optional but recommended - a suggested `ServiceRolePath` is provided in defaults)
- Parameter Store Hierarchy (optional but recommended - a suggested `ParameterStoreHierarchy` is provided in defaults)
- S3 Bucket Name Prefix (optional but recommended)
- Permission Boundaries (optional)

### Prefix

> A Prefix can be 2 to 8 characters. Lower case alphanumeric and dashes. Must start with a letter and end with a letter or number.

As stated earlier, a Prefix is a namespace that is used in resource naming and tags.

For example, an application created under the Prefix `acme` would have all of its resources named `acme-*` and tagged `atlantis:Prefix=acme`. (Except for resources that can't receive a name such as API Gateway. Then it will just be tagged with `atlantis:Prefix=acme`)

These can be used for specifying resources under `Resources` and conditionals using tags in IAM policies for Execution Roles.

Choose a Prefix that best describes the team, account, department, or function using that Prefix. You may also decide to separate out job function. For example, the finance development team may have their own AWS organization account. All developers on that team can use the `finc` Prefix. However, there may also be senior developers, or systems operators that develop solutions under the `finops` Prefix. Junior developers will be able to use `finc` but not have access to `finops` infrastructure. Senior developers may have access to both `finc` and `finops` and systems operators only have access to `finops`.

Make sure the number of Prefixes you implement remain manageable.

### Role Path

Including `RolePath` will require the `RolePath` parameter be supplied for ALL deployments.

Even though IAM doesn't provide a hierarchical structure for Roles, you can include a role path as a method for providing permissions and organization. For example, you can allow application infrastructure stacks to create Execution Roles only under the RolePath `/sam-app/`. 

### Service Role Path

Including `ServiceRolePath` will require the `RolePath` parameter be supplied for ALL Service Role deployments.

Even though IAM doesn't provide a hierarchical structure for Roles, you can include a role path as a method for providing permissions and organization. For example, you can allow service role infrastructure stacks to create only under the RolePath `/sam-svc/`.

### Parameter Store Hierarchy

Including `ParameterStoreHierarchy` will require the `ParameterStoreHierarchy` parameter be supplied for ALL deployments.

This provides a method for organizing SSM Parameter Store parameters. For example, you can require all SAM application parameters be created under `/sam-apps/`.

For example, all parameters for a test instance of an application named `checkers` under the `acme` prefix will be stored under:

```text
/sam-apps/TEST/acme-checkers-test/...
```

For Production it would be:

```text
/sam-apps/PROD/acme-checkers-prod/...
```

Note that you can allow console and CLI access to developers based upon `/<SSM_Path>/<ENV>/<prefix>-*`. The `ENV` is included first in case only senior developers or a certain class of admins should have access to PROD secrets.

### S3 Bucket Name Prefix

Including `S3BucketNameOrgPrefix` will require the `S3BucketNameOrgPrefix` parameter be supplied for ALL deployments.

While it is good practice to include the region and account in the bucket name to keep them globally unique, you can pre-pend an organizational prefix (not to be confused with the Prefix namespace) to your buckets.

For example, Acme Co may require `aco` be pre-pended.

Therefore, an application could have a bucket named `aco-acme-checkers-test-ACCT_ID-us-east-1` where `aco` is the bucket name prefix and `acme` is the namespace prefix.

Note: Using the same application namespace prefix as a bucket name prefix could cause names like `acme-acme-*`. If this bothers you then choose your S3 bucket name prefix and application namespace prefix accordingly.

### Permissions Boundaries

Permissions Boundaries can be used by administrators to limit what can and cannot be created by a user. If supplied, they must be included for ALL deployments.

This is useful for allowing the necessary creation of Execution and Service roles for applications while limiting the types of permissions these roles may create. (Not allowing the ability to create new users, or delete/modify critical account policies for instance.)

## 4. Configure defaults and settings

Update `defaults/defaults.json` and `defaults/settings.json`

#### defaults.json

If SAM has been used on your account before, AWS SAM will have created an S3 bucket with the name `cf-*`. You may use that as both the `atlantis.s3_bucket` and `parameter_overrides.S3ArtifactsBucket` values in `defaults.json`.

If you do not require a `PermissionsBoundary` then remove the arn value from `parameter_overrides.PermissionsBoundary`.

Be sure to change `atlantis.region` and `parameter_overrides.S3BucketNameOrgPrefix` for your organization.

Finally, though the rest of the values are recommended, update to suit your needs.

You may also create `*-defaults.json` for each Prefix. After creating the Pipeline service role you will include the servie role's ARN in the appropriate defaults file.

#### settings.json

Out of the box, settings.json can remain the way it is with the default values. 

##### templates

```json
{
	"templates": [
		{
			"bucket": "63klabs",
			"prefix": "atlantis/templates/v2",
			"anonymous": true
		}
	]
}
```

Out of the box you can use the public templates provided by 63klabs. This is recommended for those just getting started or using these templates for training and educational purposes.

This is an S3 bucket that acts as a central source containing all the templates and template modules to be used for pipelines, storage, roles, and networks.

If you or or organization wants to manage your own S3 bucket of templates, you can use the deployment scripts and templates found on [Atlantis Template Repository for Serverless Deployments using AWS SAM and CloudFormation](https://github.com/63Klabs/atlantis-cfn-template-repo-for-serverless-deployments) which is the source repository for the 63klabs bucket.

Because the 63klabs bucket is public, `anonymous` is set to `true`. When using your own private bucket set it to `false` and ensure your developers have permission to access it when running the cli commands for configuration and deployments.

Since `template` is an array, you can list more than one bucket.

##### app_starters

```json
{
	"app_starters": [
		{
			"bucket": "63klabs",
			"prefix": "atlantis/app-starters/v2",
			"anonymous": true
		}
	]
}
```

Like the templates bucket, this is a bucket for downloading starter code into a repository. Also, like the template bucket settings, more than one bucket may be used as a source.

Developers can run the `create_repo.py` command to automatically create a repository and seed it with starter code to quickly get started. 

The `app-starters` provided by the 63klabs bucket are zipped directly from releases of their perpective GitHub repository. For a sampling of apps available, visit the [63Klabs GitHub](https://github.com/63klabs).

Developers can also point the `--source` to any public repository or zip file when invoking the `create_repo.py` script.

##### repositories

```json
{
	"repositories": {
		"provider": "codecommit"
	}
}
```

There is only one setting for `repositories` at this time: `provider`.

This is the default provider for the `create_repo.py` script if `--provider` is not provided as a script argument.

The values are either `codecommit` or `github`.

If provider is `codecommit` when running the `create_repo` script then a CodeCommit repository is created. If it is `github` then a GitHub repository is created.

##### updates

```json
{
	"updates": {
		"source": "https://github.com/63klabs/atlantis-cfn-configuration-repo-for-serverless-deployments",
		"ver": "release:latest",
		"target_dirs": ["docs", "cli"]
	}
}
```

When running the `update.py` script, this is where the updates will come from. The `source` needs to be a public GitHub repository or an S3 bucket the user profile has access to.

The `ver` value can be locked to a specific release, the latest release, or even the latest commit (only if you are brave).

For GitHub as a source, `ver` can be:

- `commit:latest`
- `release:latest`
- `release:<tag>`

For S3 as a source, `ver` can be:

- `latest`
- `<version_id>` of the S3 object

You can specify either `docs`, `cli` or both to update. It is recommended you perform regular updates to receive the latest fixes and features.

##### regions

```json
{
	"regions": [
		"us-east-1", "us-east-2", "us-west-1", "us-west-2"
	]
}
```

Out of the box `regions` includes all available regions for AWS (as of early 2025). 

You can add or remove any region required by your organization.

##### tag_keys

These are default tags (not including default values) that are required by your organization for EVERY deployment.

You can set up default values in `defaults.json` and each Prefix's `*-defaults.json` file.

## 5. Create Pipeline Service Role

Developers will need an ARN of the service role to use for deploying application stacks using the pipeline.

Be sure to replace `acme` with your Prefix and `ADMIN_PROFILE` with a profile that has permissions to create service roles.

```bash
./cli/config.py service-role acme pipeline --profile ADMIN_PROFILE
```

After configuring the role, deploy using the `deploy.py` script (or choose Deploy Now at the end of the config.py script).

```bash
./cli/deploy.py service-role acme pipeline --profile ADMIN_PROFILE
```

Get the ARN of the service role from the output and add to the `*-defaults.json` file for the prefix.

For example, for the prefix `acme`, update `defaults/acme-defaults.json` and set `atlantis.PipelineServiceRoleArn`.

Be sure to commit your changes to the SAM config repository for others to use.

You must allow users to Assume the Role before they can use it.

## 6. Create Storage Service Role

Developers will need an ARN of the service role to use for deploying storage stacks from the script CLI.

Be sure to replace `acme` with your Prefix and `ADMIN_PROFILE` with a profile that has permissions to create service roles.

```bash
./cli/config.py service-role acme storage --profile ADMIN_PROFILE
```

After configuring the role, deploy using the `deploy.py` script (or choose Deploy Now at the end of the config.py script).

```bash
./cli/deploy.py service-role acme storage --profile ADMIN_PROFILE
```

Get the ARN of the service role from the output and add to the `*-defaults.json` file for the prefix.

For example, for the prefix `acme`, update `defaults/acme-defaults.json` and set `atlantis.StorageServiceRoleArn`.

Be sure to commit your changes to the SAM config repository for others to use.

You must allow users to Assume the Role before they can use it.

## 7. Create Network Service Role

This role will create and manage CloudFront distributions and Route53 DNS records and may not be suitable for all developers. It may be reserved for network administrators.

A template for this role has not yet been created, but you can create you own based upon the previously mentioned templates.

## Set-Up Complete

Do a run through of using the `create_repo.py`, `config.py`, and `deploy.py` scripts to ensure everything is working.

For information on using these scripts see the [In-Depth Guide](./in-depth/10-In-Depth-Guide.md)) or the [Atlantis Tutorials repository](http://github.com/63klabs/atlantis-tutorials).
