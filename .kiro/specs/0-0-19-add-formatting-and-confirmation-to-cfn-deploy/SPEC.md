# Add Formatting and Confirmation to CloudFormation Deploy

I want to minimize the differences between the two deploy branches.

## Deploy Values

Currently when deploying SAM templates that do not have an include, the CLI UI lists the values that will be used for deployment:

```
Deploying with following values
===============================
Stack name                   : acme-atlantis-mcp-storage
Region                       : us-east-2
Confirm changeset            : True
Disable rollback             : False
Deployment s3 bucket         : cf-artifacts-123456789012-us-east-2-an
Capabilities                 : ["CAPABILITY_NAMED_IAM"]
Parameter overrides          : {"Prefix": "acme", "ProjectId": "atlantis-mcp", "S3BucketNameOrgPrefix": "", "RolePath": "/sam-apps/", "AlarmNotificationEmail": "joe@example.com", "PermissionsBoundaryArn": "", "S3LogBucketName": "acme-logging-access-logs-123456789012-us-east-2-an", "InvalidatorArn": "arn:aws:lambda:us-east-2:123456789012:function:acme-cdn-invalidator-svc-prod-Ingestor"}
Signing Profiles             : {}

Initiating deployment
=====================
```

I want the same info listed before the changeset is created when using CloudFormation to deploy. 

Note that the `=====================` and headings `Deploying with following values` and `Initiating deployment` are in yellow text. Utilize the appropriate color variables used elsewhere in the scripts to provide colorized text.

## Wait for Confirmation

After the changeset is created, I would like a listing of what will change. If it can be formatted similar to sam output the better.

After the changes are listed, I want the user to be able to confirm if `confirm_changeset` = `true` or not operating in headless mode.

## Progress

Develop some sort of progress. If we cannot list CloudFormation events on a 10 second interval, or tail, then we should output lines of "Waiting for stack update to complete..." in green text. Similar to how delete.py prints text at regular intervals while waiting for deletions to complete.

## SAM Branch should remain the same

The SAM deployment branch (when there are no includes to resolve) should remain the same and unchanged.