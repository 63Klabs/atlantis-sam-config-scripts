# Set Up Account Including CloudFormation Role for Developers

> Note: This step may have already been done for you if you are provided an account from your AWS administrator. If you are working on your **personal** AWS account, then please proceed in setting it up.

If you are using an AWS Account provided for you by your administrator then skip to [Using Preconfigured AWS Account and Config Repo](./02-Using-Preconfigured-AWS-Account-and-Config-Repo.md).

If you are an AWS Account Administrator, or using your personal AWS Account, then please proceed.

## 1. Set Up Configuration Repository

The repository can reside in the repository provider of your choice (CodeCommit, GitHub, GitLab, etc).

Initialize a new repository and give it a name to promote it as the central repository for your organization's (or team or org unit's) SAM Configuration files, such as: `devops_sam-config`. Then, download and extract the Atlantis CloudFormation Configuration Repository For Serverless Deployments into your new repository.

```bash
# Downloads and extracts files for the repository
curl -L -o repo.zip "https://github.com/63klabs/atlantis-cfn-configuration-repo-for-serverless-deployments/archive/refs/heads/main.zip" && unzip -o repo.zip && DIR=$(ls -d */ | head -1) && mv "${DIR}docs" . && mv "${DIR}cli" . && mv "${DIR}defaults" . && mv "${DIR}README.md" . && mv "${DIR}.gitignore" . 2>/dev/null && rm -rf repo.zip && rm -rf "$DIR"
```

> Note: The above command pulls the latest commit from the 63Klabs repository. You can point it to a `zip` in the releases as well. However, in the end you will set up the location to retrieve updates in the settings (release, main, S3), so once you run the `update.py` script you will get the version/release you desire.

This repository will host the cli and deployment configurations for storage, network, pipeline, and IAM roles. Developers will use the cli to manage their pipeline and storage configurations and pull, commit, and push changes to maintain a central source of truth for configurations.

> It is important to **pull** any changes to the local machine, **configure** and **deploy** an infrastructure stack using the cli, and then **commit** and **push** the configuration changes back to the remote repository for proper version control.

## 2. Local Machine Set-Up

In order to run the scripts you will need to perform the Python Virtual Environment set-up as instructed in [Set-Up Local Environment](./00-Set-Up-Local-Environment.md).

## 3. Configure CloudFormation Roles for Developers

The Principle of Least Privilege is maintained through resource naming and tagging.

At the very base is the naming Prefix. The Prefix can be assigned to an entire organization account, team, or department. A single AWS account may contain multiple Prefix namespaces if the account is shared among teams or a single Prefix if a team or department is a single tenant of the account.

Any developer assigned to the team that utilizes that Prefix at the very least should have access to create and maintain a pipeline for the application they are developing. In order to create the CloudFormation stack that generates the pipeline infrastructure for application deployments, the developer must have access to assume a role that allows them to do so. The CloudFormation role they assume will grant them access to only create a pipeline under a specific Prefix. This limits their abilities to create, modify, or delete pipelines outside of the Prefix organization they are assigned to.

Additional roles may be created if the developer should be allowed to create storage or network stacks.

As of right now, only the pipeline role template is available as a starter template in this repository. However, it can be used as an example for creating additional roles for the developer to assume.

To start out, you must determine the following:

- Prefix
- Role Path (optional but recommended)
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

Even though IAM doesn't provide a heirarchical structure for Roles, you can include a role path as a method for providing permissions and organization. For example, you can allow application infrastructure stacks to create Execution Roles only under the RolePath `/app-infra/`. 

### Permissions Boundaries

Permissions Boundaries can be used by administrators to limit what can and cannot be created by a user. If supplied, they must be included for ALL deployments.

### S3 Bucket Name Prefix

This is not to be confused with Prefix or S3 object prefix. This is purely for naming the S3 bucket.

If supplied this will pre-pend this value to all S3 buckets created by infrastructure stacks (as long as it is included in the template). 

This can be used to provide permissions (requires templates to only create S3 buckets under this prefix) and shorten the bucket name. If this is not required and not supplied then bucket names will include the account and region. This makes for a unique but long name. S3 names have a limit of 63 characters. If your organization requires a prefix, it is up to you to make sure they are unique.

### Set up defaults

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

## 4. Create Pipeline Service Role

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

## 5. Create Storage Service Role

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

## Set-Up Complete

Do a run through of using the `create_repo.py`, `config.py`, and `deploy.py` scripts to ensure everything is working.

For information on using these scripts see the [In-Depth Guide](./in-depth/10-In-Depth-Guide.md)) or the [Atlantis Tutorials repository](http://github.com/63klabs/atlantis-tutorials).
